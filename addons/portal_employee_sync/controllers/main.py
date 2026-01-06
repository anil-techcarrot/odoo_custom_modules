from odoo import http
from odoo.http import request
import json
import logging

_logger = logging.getLogger(__name__)


class PortalEmployeeSyncController(http.Controller):

    def _verify_api_key(self, api_key):
        """Verify API key"""
        valid_key = "d7ce6e48fe7b6dd95283f5c36f6dd791aa83cf65"
        return api_key == valid_key

    def _extract_sharepoint_value(self, field_data):
        """Extract 'Value' from SharePoint JSON object"""
        if not field_data:
            return None

        if field_data == '':
            return None

        if isinstance(field_data, str):
            field_data = field_data.strip()
            if field_data.startswith('{') and '"Value"' in field_data:
                try:
                    parsed = json.loads(field_data)
                    value = parsed.get('Value', field_data)
                    return value if value != '' else None
                except:
                    return field_data
            return field_data if field_data != '' else None

        if isinstance(field_data, dict):
            value = field_data.get('Value', field_data)
            return value if value != '' else None

        return field_data

    @http.route('/api/employees', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def create_employee(self, **kwargs):
        """Create or update employee from SharePoint"""
        try:
            # Get API key
            api_key = request.httprequest.headers.get('api-key') or \
                      request.httprequest.headers.get('API-Key') or \
                      request.httprequest.headers.get('Authorization', '').replace('Bearer ', '')

            _logger.info(f"========== NEW EMPLOYEE REQUEST ==========")
            _logger.info(f"API Key: {api_key}")

            if not api_key or not self._verify_api_key(api_key):
                return self._json_response({
                    'error': 'Invalid API key',
                    'status': 401
                }, 401)

            # Parse JSON
            try:
                if request.httprequest.data:
                    data = json.loads(request.httprequest.data.decode('utf-8'))
                else:
                    data = request.httprequest.form.to_dict()

                _logger.info(f"📥 Received data: {json.dumps(data, indent=2)}")
            except Exception as e:
                return self._json_response({
                    'error': f'Invalid JSON: {str(e)}',
                    'status': 400
                }, 400)

            # Validate
            if not data.get('name'):
                return self._json_response({
                    'error': 'Name required',
                    'status': 400
                }, 400)

            # ═══════════════════════════════════════════════════════════
            # CHECK FOR EXISTING EMPLOYEE TO PREVENT DUPLICATES
            # ═══════════════════════════════════════════════════════════
            existing_employee = None

            # Search by email (most reliable)
            if data.get('email'):
                existing_employee = request.env['hr.employee'].sudo().search([
                    ('work_email', '=', data.get('email'))
                ], limit=1)
                if existing_employee:
                    _logger.info(f"✅ Found existing by email: {existing_employee.name} (ID: {existing_employee.id})")

            # If not found by email, search by name
            if not existing_employee and data.get('name'):
                existing_employee = request.env['hr.employee'].sudo().search([
                    ('name', '=', data.get('name'))
                ], limit=1)
                if existing_employee:
                    _logger.info(f"✅ Found existing by name: {existing_employee.name} (ID: {existing_employee.id})")

            # Determine mode
            if existing_employee:
                _logger.info(f"🔄 MODE: UPDATE existing employee")
                is_update = True
                employee = existing_employee
            else:
                _logger.info(f"🆕 MODE: CREATE new employee")
                is_update = False

            # ═══════════════════════════════════════════════════════════
            # BUILD EMPLOYEE VALUES
            # ═══════════════════════════════════════════════════════════
            employee_vals = {
                'name': data.get('name'),
                'work_email': data.get('email'),
                'mobile_phone': data.get('phone'),
                'department_id': self._get_or_create_department(data.get('department')),
                'job_id': self._get_or_create_job(data.get('job_title')),
            }

            # Name fields
            if data.get('employee_first_name'):
                employee_vals['employee_first_name'] = data.get('employee_first_name')
                _logger.info(f"✓ First Name: {data.get('employee_first_name')}")

            if data.get('employee_middle_name'):
                employee_vals['employee_middle_name'] = data.get('employee_middle_name')
                _logger.info(f"✓ Middle Name: {data.get('employee_middle_name')}")

            if data.get('employee_last_name'):
                employee_vals['employee_last_name'] = data.get('employee_last_name')
                _logger.info(f"✓ Last Name: {data.get('employee_last_name')}")

            # ═══════════════════════════════════════════════════════════
            # GENDER - WITH SHAREPOINT EXTRACTION
            # ═══════════════════════════════════════════════════════════
            if data.get('sex'):
                gender_raw = self._extract_sharepoint_value(data.get('sex'))
                _logger.info(f"📝 Gender: RAW='{data.get('sex')}' EXTRACTED='{gender_raw}'")

                if gender_raw:
                    gender_value = str(gender_raw).lower().strip()

                    gender_mapping = {
                        'male': 'male',
                        'm': 'male',
                        'female': 'female',
                        'f': 'female',
                        'other': 'other',
                    }

                    mapped_gender = gender_mapping.get(gender_value)
                    if mapped_gender:
                        employee_vals['gender'] = mapped_gender
                        _logger.info(f"✅ Gender set to: {mapped_gender}")
                    else:
                        _logger.warning(f"⚠️ Invalid gender: '{gender_value}'")

            # ═══════════════════════════════════════════════════════════
            # BIRTHDAY
            # ═══════════════════════════════════════════════════════════
            if data.get('birthday'):
                try:
                    from datetime import datetime
                    birthday_str = str(data.get('birthday')).strip()
                    _logger.info(f"📝 Processing birthday: '{birthday_str}'")

                    date_formats = [
                        '%m/%d/%Y', '%Y-%m-%d', '%d/%m/%Y',
                        '%Y/%m/%d', '%d-%m-%Y'
                    ]

                    date_obj = None
                    for fmt in date_formats:
                        try:
                            date_obj = datetime.strptime(birthday_str, fmt)
                            break
                        except:
                            continue

                    if date_obj:
                        employee_vals['birthday'] = date_obj.strftime('%Y-%m-%d')
                        _logger.info(f"✅ Birthday: {employee_vals['birthday']}")
                    else:
                        _logger.warning(f"⚠️ Could not parse birthday: '{birthday_str}'")
                except Exception as e:
                    _logger.error(f"❌ Birthday error: {e}")

            # Place of birth
            if data.get('place_of_birth'):
                employee_vals['place_of_birth'] = data.get('place_of_birth')
                _logger.info(f"✓ Place of birth: {data.get('place_of_birth')}")

            # ═══════════════════════════════════════════════════════════
            # MARITAL - WITH SHAREPOINT EXTRACTION
            # ═══════════════════════════════════════════════════════════
            if data.get('marital'):
                marital_raw = self._extract_sharepoint_value(data.get('marital'))
                _logger.info(f"📝 Marital: RAW='{data.get('marital')}' EXTRACTED='{marital_raw}'")

                if marital_raw:
                    marital_value = str(marital_raw).lower().strip()

                    marital_mapping = {
                        'single': 'single',
                        'unmarried': 'single',
                        'un married': 'single',
                        'married': 'married',
                        'cohabitant': 'cohabitant',
                        'living together': 'cohabitant',
                        'widower': 'widower',
                        'widow': 'widower',
                        'divorced': 'divorced',
                    }

                    mapped_marital = marital_mapping.get(marital_value)
                    if mapped_marital:
                        employee_vals['marital'] = mapped_marital
                        _logger.info(f"✅ Marital set to: {mapped_marital}")
                    else:
                        _logger.warning(f"⚠️ Invalid marital: '{marital_value}'")

            # Private email
            if data.get('private_email'):
                employee_vals['private_email'] = data.get('private_email')
                _logger.info(f"✓ Private email: {data.get('private_email')}")

            # ═══════════════════════════════════════════════════════════
            # COUNTRY - WITH SHAREPOINT EXTRACTION
            # ═══════════════════════════════════════════════════════════
            if data.get('country_id'):
                country_raw = self._extract_sharepoint_value(data.get('country_id'))
                _logger.info(f"📝 Country: RAW='{data.get('country_id')}' EXTRACTED='{country_raw}'")

                if country_raw:
                    country_name = str(country_raw).strip()

                    # Nationality mapping
                    nationality_map = {
                        'indian': 'India',
                        'american': 'United States',
                        'british': 'United Kingdom',
                        'emirati': 'United Arab Emirates',
                        'pakistani': 'Pakistan',
                        'bangladeshi': 'Bangladesh',
                        'sri lankan': 'Sri Lanka',
                        'nepali': 'Nepal',
                        'filipino': 'Philippines',
                    }

                    mapped_country = nationality_map.get(country_name.lower())
                    if mapped_country:
                        country_name = mapped_country
                        _logger.info(f"📍 Mapped to: {country_name}")

                    # Search country
                    country = request.env['res.country'].sudo().search([
                        ('name', '=', country_name)
                    ], limit=1)

                    if not country:
                        country = request.env['res.country'].sudo().search([
                            '|',
                            ('name', 'ilike', country_name),
                            ('code', '=ilike', country_name)
                        ], limit=1)

                    if country:
                        employee_vals['country_id'] = country.id
                        _logger.info(f"✅ Country: {country.name}")
                    else:
                        _logger.warning(f"⚠️ Country not found: '{country_name}'")

            # ═══════════════════════════════════════════════════════════
            # MOTHER TONGUE - WITH SHAREPOINT EXTRACTION
            # ═══════════════════════════════════════════════════════════
            if data.get('mother_tongue_id'):
                lang_raw = self._extract_sharepoint_value(data.get('mother_tongue_id'))
                _logger.info(f"📝 Mother Tongue: RAW='{data.get('mother_tongue_id')}' EXTRACTED='{lang_raw}'")

                if lang_raw:
                    lang_name = str(lang_raw).strip()

                    lang = request.env['res.lang'].sudo().search([
                        '|', '|', '|',
                        ('name', '=ilike', lang_name),
                        ('name', 'ilike', lang_name),
                        ('iso_code', '=ilike', lang_name),
                        ('code', '=ilike', lang_name)
                    ], limit=1)

                    if lang:
                        employee_vals['mother_tongue_id'] = lang.id
                        _logger.info(f"✅ Mother Tongue: {lang.name}")
                    else:
                        _logger.warning(f"⚠️ Language not found: '{lang_name}'")

            # ═══════════════════════════════════════════════════════════
            # LANGUAGES KNOWN - WITH SHAREPOINT EXTRACTION
            # ═══════════════════════════════════════════════════════════
            if data.get('language_known_ids'):
                try:
                    lang_raw = self._extract_sharepoint_value(data.get('language_known_ids'))
                    _logger.info(f"📝 Languages: RAW='{data.get('language_known_ids')}' EXTRACTED='{lang_raw}'")

                    if lang_raw:
                        lang_string = str(lang_raw).strip()
                        lang_names = [l.strip() for l in lang_string.split(',') if l.strip()]
                        _logger.info(f"📋 Split: {lang_names}")

                        if lang_names:
                            found_langs = request.env['res.lang'].sudo()

                            for lang_name in lang_names:
                                lang = request.env['res.lang'].sudo().search([
                                    '|', '|', '|',
                                    ('name', '=ilike', lang_name),
                                    ('name', 'ilike', lang_name),
                                    ('iso_code', '=ilike', lang_name),
                                    ('code', '=ilike', lang_name)
                                ], limit=1)

                                if lang:
                                    found_langs |= lang
                                    _logger.info(f"  ✓ Found: {lang.name}")
                                else:
                                    _logger.warning(f"  ✗ Not found: {lang_name}")

                            if found_langs:
                                employee_vals['language_known_ids'] = [(6, 0, found_langs.ids)]
                                _logger.info(f"✅ Languages: {', '.join(found_langs.mapped('name'))}")

                except Exception as e:
                    _logger.error(f"❌ Languages error: {e}")

            # ═══════════════════════════════════════════════════════════
            # CREATE OR UPDATE EMPLOYEE
            # ═══════════════════════════════════════════════════════════
            _logger.info(f"📦 Employee values: {json.dumps(employee_vals, default=str, indent=2)}")

            if is_update:
                # UPDATE existing employee
                _logger.info(f"🔄 Updating employee ID: {employee.id}")
                employee.write(employee_vals)
                _logger.info(f"✅ UPDATED: {employee.name} (ID: {employee.id})")
                message = 'Employee updated successfully'
                status = 'updated'
            else:
                # CREATE new employee
                _logger.info(f"🆕 Creating new employee")
                employee = request.env['hr.employee'].sudo().create(employee_vals)
                _logger.info(f"✅ CREATED: {employee.name} (ID: {employee.id})")
                message = 'Employee created successfully'
                status = 'created'

            _logger.info(f"========== REQUEST COMPLETE ==========\n")

            # Return response
            return self._json_response({
                'success': True,
                'status': status,
                'employee_id': employee.id,
                'message': message,
                'data': {
                    'id': employee.id,
                    'name': employee.name,
                    'email': employee.work_email or '',
                    'phone': employee.mobile_phone or '',
                    'first_name': employee.employee_first_name or '',
                    'middle_name': employee.employee_middle_name or '',
                    'last_name': employee.employee_last_name or '',
                    'department': employee.department_id.name if employee.department_id else '',
                    'job_title': employee.job_id.name if employee.job_id else '',
                    'gender': employee.gender or '',
                    'birthday': employee.birthday.strftime('%Y-%m-%d') if employee.birthday else '',
                    'place_of_birth': employee.place_of_birth or '',
                    'marital': employee.marital or '',
                    'private_email': employee.private_email or '',
                    'country': employee.country_id.name if employee.country_id else '',
                    'mother_tongue': employee.mother_tongue_id.name if employee.mother_tongue_id else '',
                    'languages_known': ', '.join(
                        employee.language_known_ids.mapped('name')) if employee.language_known_ids else '',
                }
            })

        except Exception as e:
            _logger.error(f"❌ ERROR: {str(e)}", exc_info=True)
            return self._json_response({
                'error': str(e),
                'status': 500
            }, 500)

    @http.route('/api/employees', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def get_employees(self, **kwargs):
        """Get all employees"""
        try:
            api_key = request.httprequest.headers.get('api-key') or \
                      request.httprequest.headers.get('API-Key') or \
                      request.httprequest.headers.get('Authorization', '').replace('Bearer ', '')

            if not api_key or not self._verify_api_key(api_key):
                return self._json_response({
                    'error': 'Invalid API key',
                    'status': 401
                }, 401)

            employees = request.env['hr.employee'].sudo().search([])

            employee_list = []
            for emp in employees:
                employee_list.append({
                    'id': emp.id,
                    'name': emp.name,
                    'email': emp.work_email or '',
                    'phone': emp.mobile_phone or '',
                    'first_name': emp.employee_first_name or '',
                    'middle_name': emp.employee_middle_name or '',
                    'last_name': emp.employee_last_name or '',
                    'department': emp.department_id.name if emp.department_id else '',
                    'job_title': emp.job_id.name if emp.job_id else '',
                    'gender': emp.gender or '',
                    'marital': emp.marital or '',
                    'mother_tongue': emp.mother_tongue_id.name if emp.mother_tongue_id else '',
                    'languages_known': ', '.join(
                        emp.language_known_ids.mapped('name')) if emp.language_known_ids else '',
                })

            return self._json_response({
                'success': True,
                'status': 'success',
                'count': len(employee_list),
                'employees': employee_list
            })

        except Exception as e:
            _logger.error(f"Error: {str(e)}")
            return self._json_response({
                'error': str(e),
                'status': 500
            }, 500)

    def _get_or_create_department(self, dept_name):
        """Get or create department"""
        if not dept_name:
            return False

        department = request.env['hr.department'].sudo().search([
            ('name', '=', dept_name)
        ], limit=1)

        if not department:
            department = request.env['hr.department'].sudo().create({
                'name': dept_name
            })
            _logger.info(f"Created department: {dept_name}")

        return department.id

    def _get_or_create_job(self, job_title):
        """Get or create job"""
        if not job_title:
            return False

        job = request.env['hr.job'].sudo().search([
            ('name', '=', job_title)
        ], limit=1)

        if not job:
            job = request.env['hr.job'].sudo().create({
                'name': job_title
            })
            _logger.info(f"Created job: {job_title}")

        return job.id

    def _json_response(self, data, status=200):
        """JSON response"""
        return request.make_response(
            json.dumps(data, indent=2),
            headers=[
                ('Content-Type', 'application/json'),
                ('Access-Control-Allow-Origin', '*'),
            ],
            status=status
        )