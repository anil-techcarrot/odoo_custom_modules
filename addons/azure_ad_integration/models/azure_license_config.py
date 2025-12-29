import requests
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class AzureLicenseConfig(models.Model):
    _name = 'azure.license.config'
    _description = 'Azure License Configuration'
    _rec_name = 'license_name'

    license_name = fields.Char("License Name", readonly=True)
    license_sku = fields.Char("License SKU", readonly=True)
    total_licenses = fields.Integer("Total Licenses", readonly=True)
    assigned_licenses = fields.Integer("Assigned Licenses", readonly=True)
    available_licenses = fields.Integer("Available Licenses", compute='_compute_available', store=True)
    last_sync = fields.Datetime("Last Synced", readonly=True)

    @api.depends('total_licenses', 'assigned_licenses')
    def _compute_available(self):
        for record in self:
            record.available_licenses = record.total_licenses - record.assigned_licenses

    def action_sync_licenses_from_azure(self):
        """Fetch license info from Azure"""
        params = self.env['ir.config_parameter'].sudo()
        tenant = params.get_param("azure_tenant_id")
        client = params.get_param("azure_client_id")
        secret = params.get_param("azure_client_secret")

        if not all([tenant, client, secret]):
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': 'Azure credentials missing',
                    'type': 'danger',
                }
            }

        try:
            # Get token
            token_resp = requests.post(
                f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": client,
                    "client_secret": secret,
                    "scope": "https://graph.microsoft.com/.default"
                },
                timeout=30
            ).json()

            token = token_resp.get("access_token")
            if not token:
                _logger.error("❌ No token")
                return

            headers = {"Authorization": f"Bearer {token}"}

            # Get all subscribed SKUs
            response = requests.get(
                "https://graph.microsoft.com/v1.0/subscribedSkus",
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                skus = response.json().get('value', [])

                # Clear old records
                self.search([]).unlink()

                # Create new records for each license
                for sku in skus:
                    self.create({
                        'license_name': sku.get('skuPartNumber'),
                        'license_sku': sku.get('skuId'),
                        'total_licenses': sku.get('prepaidUnits', {}).get('enabled', 0),
                        'assigned_licenses': sku.get('consumedUnits', 0),
                        'last_sync': fields.Datetime.now()
                    })

                _logger.info(f"✅ Synced {len(skus)} license types")

                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'message': f'✅ Synced {len(skus)} license types from Azure',
                        'type': 'success',
                    }
                }
            else:
                _logger.error(f"❌ Failed to get licenses: {response.status_code}")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'message': 'Failed to sync licenses from Azure',
                        'type': 'danger',
                    }
                }

        except Exception as e:
            _logger.error(f"❌ Error: {e}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f'Error: {str(e)}',
                    'type': 'danger',
                }
            }