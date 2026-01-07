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

    @http.route('/api/employees', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def create_employee(self, **kwargs):
        """Create OR UPDATE employee from external system with all SharePoint fields"""
        try:
            # Get API key from headers
            api_key = request.httprequest.headers.get('api-key') or \
                      request.httprequest.headers.get('API-Key') or \
                      request.httprequest.headers.get('Authorization', '').replace('Bearer ', '')

            _logger.info(f"========== NEW EMPLOYEE REQUEST ==========")
            _logger.info(f"Received API Key: {api_key}")

            if not api_key or not self._verify_api_key(api_key):
                return self._json_response({
                    'error': 'Invalid API key',
                    'status': 401
                }, 401)

            # Parse JSON data from request body
            try:
                if request.httprequest.data:
                    data = json.loads(request.httprequest.data.decode('utf-8'))
                else:
                    data = request.httprequest.form.to_dict()

                _logger.info(f"📥 RAW DATA RECEIVED:")
                _logger.info(f"{json.dumps(data, indent=2)}")

                # DEBUG: Log each field individually
                _logger.info(f"\n🔍 FIELD-BY-FIELD ANALYSIS:")
                _logger.info(f"  name: '{data.get('name')}' (type: {type(data.get('name'))})")
                _logger.info(f"  sex/gender: '{data.get('sex')}' (type: {type(data.get('sex'))})")
                _logger.info(f"  birthday: '{data.get('birthday')}' (type: {type(data.get('birthday'))})")
                _logger.info(f"  marital: '{data.get('marital')}' (type: {type(data.get('marital'))})")
                _logger.info(
                    f"  mother_tongue_id: '{data.get('mother_tongue_id')}' (type: {type(data.get('mother_tongue_id'))})")
                _logger.info(
                    f"  language_known_ids: '{data.get('language_known_ids')}' (type: {type(data.get('language_known_ids'))})")
                _logger.info(f"  country_id: '{data.get('country_id')}' (type: {type(data.get('country_id'))})")

            except Exception as e:
                return self._json_response({
                    'error': f'Invalid JSON: {str(e)}',
                    'status': 400
                }, 400)

            # Validate required field
            if not data.get('name'):
                return self._json_response({
                    'error': 'Name required',
                    'status': 400
                }, 400)

            # ============================================
            # CHECK IF EMPLOYEE EXISTS
            # ============================================
            existing_employee = None

            if data.get('employee_id'):
                existing_employee = request.env['hr.employee'].sudo().search([
                    ('sharepoint_employee_id', '=', str(data.get('employee_id')))
                ], limit=1)
                if existing_employee:
                    _logger.info(f"✅ Found existing employee by SharePoint ID: {data.get('employee_id')}")

            if not existing_employee and data.get('name'):
                existing_employee = request.env['hr.employee'].sudo().search([
                    ('name', '=', data.get('name'))
                ], limit=1)
                if existing_employee:
                    _logger.info(f"✅ Found existing employee by Name: {data.get('name')}")

            if not existing_employee:
                if data.get('employee_first_name') and data.get('employee_last_name'):
                    existing_employee = request.env['hr.employee'].sudo().search([
                        ('employee_first_name', '=', data.get('employee_first_name')),
                        ('employee_last_name', '=', data.get('employee_last_name'))
                    ], limit=1)
                    if existing_employee:
                        _logger.info(f"✅ Found existing employee by First+Last Name")

            # BASE EMPLOYEE DATA
            employee_vals = {
                'name': data.get('name'),
                'mobile_phone': data.get('phone'),
                'department_id': self._get_or_create_department(data.get('department')),
                'job_id': self._get_or_create_job(data.get('job_title')),
            }

            # Add SharePoint Employee ID
            if data.get('employee_id'):
                employee_vals['sharepoint_employee_id'] = str(data.get('employee_id'))

            # Only set work_email if employee doesn't exist
            if not existing_employee:
                employee_vals['work_email'] = data.get('email')
                _logger.info(f"📧 Setting work_email for NEW employee: {data.get('email')}")
            else:
                _logger.info(f"📧 SKIPPING work_email - employee exists: {existing_employee.work_email}")

            # SHAREPOINT NAME FIELDS
            if data.get('employee_first_name'):
                employee_vals['employee_first_name'] = data.get('employee_first_name')
                _logger.info(f"✓ First Name: {data.get('employee_first_name')}")

            if data.get('employee_middle_name'):
                employee_vals['employee_middle_name'] = data.get('employee_middle_name')
                _logger.info(f"✓ Middle Name: {data.get('employee_middle_name')}")

            if data.get('employee_last_name'):
                employee_vals['employee_last_name'] = data.get('employee_last_name')
                _logger.info(f"✓ Last Name: {data.get('employee_last_name')}")

            # GENDER - ENHANCED LOGGING
            if data.get('sex'):
                gender_value = str(data.get('sex')).lower().strip()
                _logger.info(f"📝 RAW Gender value: '{data.get('sex')}'")
                _logger.info(f"📝 Cleaned Gender value: '{gender_value}'")

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
                    _logger.info(f"✅ Gender WILL BE SET to: {mapped_gender}")
                else:
                    _logger.error(f"❌ GENDER MAPPING FAILED for: '{gender_value}'")
                    _logger.error(f"   Valid options: {list(gender_mapping.keys())}")
            else:
                _logger.warning(f"⚠️ No 'sex' field in data - Gender will NOT be set")

            # BIRTHDAY - ENHANCED LOGGING
            if data.get('birthday'):
                try:
                    from datetime import datetime
                    birthday_str = str(data.get('birthday')).strip()
                    _logger.info(f"📝 RAW Birthday: '{data.get('birthday')}'")
                    _logger.info(f"📝 Cleaned Birthday: '{birthday_str}'")

                    date_obj = None
                    date_formats = [
                        '%m/%d/%Y',  # 01/15/1990
                        '%Y-%m-%d',  # 1990-01-15
                        '%d/%m/%Y',  # 15/01/1990
                        '%Y/%m/%d',  # 1990/01/15
                        '%d-%m-%Y',  # 15-01-1990
                    ]

                    for fmt in date_formats:
                        try:
                            date_obj = datetime.strptime(birthday_str, fmt)
                            _logger.info(f"✅ Birthday parsed with format: {fmt}")
                            break
                        except:
                            continue

                    if date_obj:
                        employee_vals['birthday'] = date_obj.strftime('%Y-%m-%d')
                        _logger.info(f"✅ Birthday WILL BE SET to: {employee_vals['birthday']}")
                    else:
                        _logger.error(f"❌ BIRTHDAY PARSING FAILED for: '{birthday_str}'")
                        _logger.error(f"   Tried formats: {date_formats}")

                except Exception as e:
                    _logger.error(f"❌ Birthday Exception: {e}")
            else:
                _logger.warning(f"⚠️ No 'birthday' field in data")

            # PLACE OF BIRTH
            if data.get('place_of_birth'):
                employee_vals['place_of_birth'] = data.get('place_of_birth')
                _logger.info(f"✓ Place of birth: {data.get('place_of_birth')}")

            # MARITAL STATUS - ENHANCED LOGGING
            if data.get('marital'):
                marital_value = str(data.get('marital')).lower().strip()
                _logger.info(f"📝 RAW Marital: '{data.get('marital')}'")
                _logger.info(f"📝 Cleaned Marital: '{marital_value}'")

                marital_mapping = {
                    'single': 'single',
                    'unmarried': 'single',
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
                    _logger.info(f"✅ Marital WILL BE SET to: {mapped_marital}")
                else:
                    _logger.error(f"❌ MARITAL MAPPING FAILED for: '{marital_value}'")
                    _logger.error(f"   Valid options: {list(marital_mapping.keys())}")
            else:
                _logger.warning(f"⚠️ No 'marital' field in data")

            # PRIVATE EMAIL
            if data.get('private_email'):
                employee_vals['private_email'] = data.get('private_email')
                _logger.info(f"✓ Private email: {data.get('private_email')}")

            # NATIONALITY (COUNTRY) - ENHANCED LOGGING
            if data.get('country_id'):
                country_name = str(data.get('country_id')).strip()
                _logger.info(f"📝 RAW Country: '{data.get('country_id')}'")
                _logger.info(f"📝 Searching for country: '{country_name}'")

                country = request.env['res.country'].sudo().search([
                    '|', '|',
                    ('name', '=ilike', country_name),
                    ('name', 'ilike', country_name),
                    ('code', '=ilike', country_name)
                ], limit=1)

                if country:
                    employee_vals['country_id'] = country.id
                    _logger.info(f"✅ Country WILL BE SET to: {country.name} (ID: {country.id})")
                else:
                    _logger.error(f"❌ COUNTRY NOT FOUND: '{country_name}'")
                    sample_countries = request.env['res.country'].sudo().search([], limit=10)
                    _logger.error(f"   Sample countries in Odoo: {', '.join(sample_countries.mapped('name'))}")
            else:
                _logger.warning(f"⚠️ No 'country_id' field in data")

            # MOTHER TONGUE - ENHANCED LOGGING
            if data.get('mother_tongue_id'):
                lang_name = str(data.get('mother_tongue_id')).strip()
                _logger.info(f"📝 RAW Mother Tongue: '{data.get('mother_tongue_id')}'")
                _logger.info(f"📝 Searching for language: '{lang_name}'")

                # Show available languages
                available_langs = request.env['res.lang'].sudo().search([])
                _logger.info(f"📋 Available languages: {', '.join(available_langs.mapped('name'))}")

                lang = request.env['res.lang'].sudo().search([
                    '|', '|', '|',
                    ('name', '=ilike', lang_name),
                    ('name', 'ilike', lang_name),
                    ('iso_code', '=ilike', lang_name),
                    ('code', '=ilike', lang_name)
                ], limit=1)

                if lang:
                    employee_vals['mother_tongue_id'] = lang.id
                    _logger.info(f"✅ Mother Tongue WILL BE SET to: {lang.name} (ID: {lang.id})")
                else:
                    _logger.error(f"❌ LANGUAGE NOT FOUND: '{lang_name}'")
                    _logger.error(f"   Make sure it's installed in Odoo (Settings → Languages)")
            else:
                _logger.warning(f"⚠️ No 'mother_tongue_id' field in data")

            # LANGUAGES KNOWN - ENHANCED LOGGING
            if data.get('language_known_ids'):
                try:
                    lang_string = str(data.get('language_known_ids')).strip()
                    _logger.info(f"📝 RAW Languages Known: '{data.get('language_known_ids')}'")
                    _logger.info(f"📝 Processing languages: '{lang_string}'")

                    lang_names = [l.strip() for l in lang_string.split(',') if l.strip()]
                    _logger.info(f"📋 Split into {len(lang_names)} languages: {lang_names}")

                    if lang_names:
                        found_langs = request.env['res.lang'].sudo()

                        for lang_name in lang_names:
                            _logger.info(f"  🔍 Searching for: '{lang_name}'")
                            lang = request.env['res.lang'].sudo().search([
                                '|', '|', '|',
                                ('name', '=ilike', lang_name),
                                ('name', 'ilike', lang_name),
                                ('iso_code', '=ilike', lang_name),
                                ('code', '=ilike', lang_name)
                            ], limit=1)

                            if lang:
                                found_langs |= lang
                                _logger.info(f"  ✅ Found: {lang.name}")
                            else:
                                _logger.error(f"  ❌ NOT FOUND: '{lang_name}'")

                        if found_langs:
                            employee_vals['language_known_ids'] = [(6, 0, found_langs.ids)]
                            _logger.info(f"✅ Languages WILL BE SET to: {', '.join(found_langs.mapped('name'))}")
                        else:
                            _logger.error(f"❌ NO LANGUAGES FOUND from: {lang_names}")
                    else:
                        _logger.warning(f"⚠️ Languages string is empty after split")

                except Exception as e:
                    _logger.error(f"❌ Languages Exception: {e}")
            else:
                _logger.warning(f"⚠️ No 'language_known_ids' field in data")

            # ============================================
            # CREATE OR UPDATE EMPLOYEE
            # ============================================
            _logger.info(f"\n📦 FINAL employee_vals BEFORE CREATE/UPDATE:")
            _logger.info(f"{json.dumps(employee_vals, default=str, indent=2)}")

            if existing_employee:
                _logger.info(f"📝 UPDATING existing employee: {existing_employee.name} (ID: {existing_employee.id})")
                existing_employee.write(employee_vals)
                employee = existing_employee
                _logger.info(f"✅ Employee UPDATED")
            else:
                _logger.info(f"🆕 CREATING new employee")
                employee = request.env['hr.employee'].sudo().create(employee_vals)
                _logger.info(f"✅ Employee CREATED (ID: {employee.id})")

            # VERIFY WHAT WAS ACTUALLY SAVED
            _logger.info(f"\n🔍 VERIFICATION - What was saved in database:")
            _logger.info(f"  Gender: {employee.gender}")
            _logger.info(f"  Birthday: {employee.birthday}")
            _logger.info(f"  Marital: {employee.marital}")
            _logger.info(f"  Mother Tongue: {employee.mother_tongue_id.name if employee.mother_tongue_id else 'None'}")
            _logger.info(
                f"  Languages: {', '.join(employee.language_known_ids.mapped('name')) if employee.language_known_ids else 'None'}")
            _logger.info(f"  Country: {employee.country_id.name if employee.country_id else 'None'}")

            _logger.info(f"========== REQUEST COMPLETE ==========\n")

            # RETURN DETAILED RESPONSE
            return self._json_response({
                'success': True,
                'status': 'success',
                'employee_id': employee.id,
                'message': f'Employee {"updated" if existing_employee else "created"} successfully',
                'action': 'update' if existing_employee else 'create',
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
                    'sharepoint_id': employee.sharepoint_employee_id or '',
                }
            })

        except Exception as e:
            _logger.error(f"❌ FATAL ERROR: {str(e)}", exc_info=True)
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
                    'sharepoint_id': emp.sharepoint_employee_id or '',
                })

            return self._json_response({
                'success': True,
                'status': 'success',
                'count': len(employee_list),
                'employees': employee_list
            })

        except Exception as e:
            _logger.error(f"Error fetching employees: {str(e)}")
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
            _logger.info(f"Created new department: {dept_name}")

        return department.id

    def _get_or_create_job(self, job_title):
        """Get or create job position"""
        if not job_title:
            return False

        job = request.env['hr.job'].sudo().search([
            ('name', '=', job_title)
        ], limit=1)

        if not job:
            job = request.env['hr.job'].sudo().create({
                'name': job_title
            })
            _logger.info(f"Created new job: {job_title}")

        return job.id

    def _json_response(self, data, status=200):
        """Return JSON response with proper headers"""
        return request.make_response(
            json.dumps(data, indent=2),
            headers=[
                ('Content-Type', 'application/json'),
                ('Access-Control-Allow-Origin', '*'),
            ],
            status=status
        )