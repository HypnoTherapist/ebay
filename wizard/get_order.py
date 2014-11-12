# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2012-Today OpenERP SA (<http://www.openerp.com>)
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>
#
##############################################################################

from openerp import tools
from openerp.osv import osv
from openerp.osv import fields
from openerp.tools.translate import _

from openerp.addons.ebay.ebay_utils import *

class get_order(osv.TransientModel):
    _name = 'ebay.getorder'
    _description = 'eBay Get Orders'
    
    _columns = {
        'number_of_days': fields.selection([
            ('1', '1'),
            ('2', '2'),
            ('3', '3'),
            ('5', '5'),
            ('7', '7'),
            ('15', '15'),
            ('30', '30'),
            ], 'Number Of Days', help='''
            This filter specifies the number of days (24-hour periods) in the past to search for orders.
            All eBay orders that were either created or modified within this period are returned in the output.
            '''),
        'sandbox_user_included': fields.boolean ('Sandbox User Included'),
    }
    
    _defaults = {
        'number_of_days': '2',
        'sandbox_user_included': False,
    }
    
    def _search_country_id(self, cr, uid, country, country_name, context=None):
        res_country_obj = self.pool.get('res.country')
        domain = [('code', '=', country)]
        ids = res_country_obj.search(cr, uid, domain, context=context)
        if not ids:
            ids = dict()
            vals = dict()
            vals['name'] = country_name
            vals['code'] = country
            ids[0] = res_country_obj.create(cr, uid, vals, context=context)
        return ids[0]
    
    def _search_state_id(self, cr, uid, country_id, state_or_province, context=None):
        res_country_state_obj = self.pool.get('res.country.state')
        domain = [('country_id', '=', country_id), ('name', '=', state_or_province)]
        ids = res_country_state_obj.search(cr, uid, domain, context=context)
        if not ids:
            ids = dict()
            vals = dict()
            vals['country_id'] = country_id
            vals['name'] = state_or_province
            vals['code'] = 'ABC'
            ids[0] = res_country_state_obj.create(cr, uid, vals, context=context)
        return ids[0]
    
    def action_sync(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        this = self.browse(cr, uid, ids)[0]
        ebay_ebay_obj = self.pool.get('ebay.ebay')
        ebay_item_obj = self.pool.get('ebay.item')
        res_partner_obj = self.pool.get('res.partner')
        ebay_sale_order_obj = self.pool.get('ebay.sale.order')
        ebay_sale_order_transaction_obj = self.pool.get('ebay.sale.order.transaction')
        pricelist_id = self.pool.get('product.pricelist').search(cr, uid, [], context=context)[0]
        for user in ebay_ebay_obj.get_auth_user(cr, uid, this.sandbox_user_included, context=context):
            output_selector = [
                'HasMoreOrders',
                'OrderArray.Order.AdjustmentAmount',
                'OrderArray.Order.AmountPaid',
                'OrderArray.Order.AmountSaved',
                'OrderArray.Order.BuyerCheckoutMessage',
                'OrderArray.Order.BuyerUserID',
                'OrderArray.Order.CancelReason',
                'OrderArray.Order.CheckoutStatus',
                'OrderArray.Order.CreatedTime',
                'OrderArray.Order.CreatingUserRole',
                'OrderArray.Order.OrderID',
                'OrderArray.Order.OrderStatus',
                'OrderArray.Order.PaidTime',
                'OrderArray.Order.PaymentHoldStatus',
                'OrderArray.Order.ShippedTime',
                'OrderArray.Order.ShippingAddress',
                'OrderArray.Order.ShippingDetails.SellingManagerSalesRecordNumber',
                'OrderArray.Order.Subtotal',
                'OrderArray.Order.Total',
                'OrderArray.Order.TransactionArray.Transaction.ActualHandlingCost',
                'OrderArray.Order.TransactionArray.Transaction.ActualShippingCost',
                'OrderArray.Order.TransactionArray.Transaction.Buyer',
                'OrderArray.Order.TransactionArray.Transaction.CreatedDate',
                'OrderArray.Order.TransactionArray.Transaction.FinalValueFee',
                'OrderArray.Order.TransactionArray.Transaction.Item',
                'OrderArray.Order.TransactionArray.Transaction.OrderLineItemID',
                'OrderArray.Order.TransactionArray.Transaction.QuantityPurchased',
                'OrderArray.Order.TransactionArray.Transaction.ShippedTime',
                'OrderArray.Order.TransactionArray.Transaction.ShippingDetails.SellingManagerSalesRecordNumber',
                'OrderArray.Order.TransactionArray.Transaction.Status',
                'OrderArray.Order.TransactionArray.Transaction.TransactionID',
                'OrderArray.Order.TransactionArray.Transaction.TransactionPrice',
                'OrderArray.Order.TransactionArray.Transaction.UnpaidItem',
                'OrderArray.Order.TransactionArray.Transaction.Variation',
                'OrdersPerPage',
                'PageNumber',
                'ReturnedOrderCountActual',
            ]
            entries_per_page = 75
            page_number = 1
            has_more_orders = True
            while has_more_orders:
                call_data=dict()
                call_data['IncludeFinalValueFee'] = True
                call_data['NumberOfDays'] = this.number_of_days
                call_data['OrderStatus'] = 'Completed'
                call_data['Pagination'] = {
                    'EntriesPerPage': entries_per_page,
                    'PageNumber': page_number,
                }
                error_msg = 'Get the orders for the specified user %s' % user.name
                reply = ebay_ebay_obj.call(cr, uid, user, 'GetOrders', call_data, error_msg, context=context).response.reply
                has_more_orders = reply.HasMoreOrders == 'true'
                if not reply.OrderArray:
                    raise osv.except_osv(_('No order found!'), _('No OrderArray returned.'))
                orders = reply.OrderArray.Order
                if type(orders) != list:
                    orders = [orders]
                for order in orders:
                    # find existing order
                    domain = [('order_id', '=', order.OrderID)]
                    ids = ebay_sale_order_obj.search(cr, uid, domain, context=context)
                    if ids:
                        sale_order = ebay_sale_order_obj.browse(cr, uid, ids[0], context=context)
                        last_modified_time = order.CheckoutStatus.LastModifiedTime
                        if sale_order.cs_last_modified_time != ebay_strftime(last_modified_time):
                            # last modified
                            vals = dict()
                            if order.has_key('CancelReason'):
                                vals['cancel_reason'] = order.CancelReason
                            checkout_status = order.CheckoutStatus
                            vals['cs_last_modified_time'] = checkout_status.LastModifiedTime
                            vals['cs_ebay_payment_status'] = checkout_status.eBayPaymentStatus
                            vals['cs_payment_method'] = checkout_status.PaymentMethod
                            vals['cs_status'] = checkout_status.Status
                            vals['order_status'] = order.OrderStatus
                            if order.has_key('PaidTime'):
                                vals['paid_time'] = order.PaidTime
                            vals['payment_hold_status'] = order.PaymentHoldStatus
                            vals['sd_record_number'] = order.ShippingDetails.SellingManagerSalesRecordNumber
                            vals['shipped_time'] = order.ShippedTime
                            vals['state'] = 'sent'
                            sale_order.write(vals)
                    else:
                        # finding existing customer
                        partner_id = -1
                        address_id = order.ShippingAddress.AddressID
                        domain = [('address_id', '=', address_id)]
                        ids = res_partner_obj.search(cr, uid, domain, context=context)
                        if ids:
                            partner_id = ids[0]
                        else:
                            # create new customer
                            shipping_address = order.ShippingAddress
                            vals = dict()
                            vals['from_ebay'] = True
                            vals['address_id'] = address_id
                            vals['address_owner'] = shipping_address.AddressOwner
                            vals['city'] = shipping_address.CityName
                            vals['name'] = shipping_address.Name
                            if shipping_address.has_key('Phone'):
                                vals['phone'] = shipping_address.Phone
                            vals['zip'] = shipping_address.PostalCode
                            vals['street'] = shipping_address.Street1
                            if shipping_address.has_key('Street2'):
                                vals['street2'] = shipping_address.Street2
                            country = shipping_address.Country
                            country_name = shipping_address.CountryName
                            country_id = self._search_country_id(cr, uid, country, country_name, context=context)
                            vals['country_id'] = country_id
                            state_or_province = shipping_address.StateOrProvince
                            if state_or_province:
                                vals['state_id'] = self._search_state_id(cr, uid, country_id, state_or_province, context=context)
                            partner_id = res_partner_obj.create(cr, uid, vals, context=context)
                        partner = res_partner_obj.browse(cr, uid, partner_id, context=context)
                            
                        # create new order
                        vals = dict()
                        vals['adjustment_amount'] = order.AdjustmentAmount.value
                        vals['amount_paid'] = order.AmountPaid.value
                        vals['amount_saved'] = order.AmountSaved.value
                        if order.has_key('BuyerCheckoutMessage'):
                            vals['buyer_checkout_message'] = order.BuyerCheckoutMessage
                        vals['buyer_user_id'] = order.BuyerUserID
                        if order.has_key('CancelReason'):
                            vals['cancel_reason'] = order.CancelReason
                        vals['created_time'] = order.CreatedTime
                        checkout_status = order.CheckoutStatus
                        vals['cs_last_modified_time'] = checkout_status.LastModifiedTime
                        vals['cs_ebay_payment_status'] = checkout_status.eBayPaymentStatus
                        vals['cs_payment_method'] = checkout_status.PaymentMethod
                        vals['cs_status'] = checkout_status.Status
                        vals['order_id'] = order.OrderID
                        vals['order_status'] = order.OrderStatus
                        if order.has_key('PaidTime'):
                            vals['paid_time'] = order.PaidTime
                        vals['payment_hold_status'] = order.PaymentHoldStatus
                        vals['sd_record_number'] = order.ShippingDetails.SellingManagerSalesRecordNumber
                        if order.has_key('ShippedTime'):
                            vals['shipped_time'] = order.ShippedTime
                            vals['state'] = 'sent'
                        vals['shipping_service'] = user.shipping_service
                        vals['subtotal'] = order.Subtotal.value
                        vals['total'] = order.Total.value
                        vals['partner_id'] = partner_id
                        vals['ebay_user_id'] = user.id
                        
                        sale_order_id = ebay_sale_order_obj.create(cr, uid, vals, context=context)
                        
                        # add transactions
                        transactions = order.TransactionArray.Transaction
                        if type(transactions) != list:
                            transactions = [transactions]
                        for transaction in transactions:
                            # create new sale order line
                            vals = dict()
                            
                            vals['actual_handling_cost'] = transaction.ActualHandlingCost.value
                            vals['actual_shipping_cost'] = transaction.ActualShippingCost.value
                            if not partner.email and transaction.Buyer.has_key('Email'):
                                partner.write(dict(email=transaction.Buyer.Email))
                                partner.refresh()
                            vals['created_date'] = transaction.CreatedDate
                            vals['final_value_fee'] = transaction.FinalValueFee.value
                            
                            vals['order_id'] = sale_order_id
                            vals['order_line_item_id'] = transaction.OrderLineItemID
                            vals['quantity_purchased'] = transaction.QuantityPurchased
                            vals['sd_record_number'] = transaction.ShippingDetails.SellingManagerSalesRecordNumber
                            if order.has_key('ShippedTime'):
                                vals['shipped_time'] = order.ShippedTime
                                vals['state'] = 'done'
                            vals['transaction_id'] = transaction.TransactionID
                            vals['transaction_price'] = transaction.TransactionPrice.value
                            vals['item_id'] = transaction.Item.ItemID
                            sku = transaction.Item.SKU if transaction.Item.has_key('SKU') else ''
                            if sku and sku.isdigit() and ebay_item_obj.exists(cr, uid, int(sku), context=context):
                                vals['ebay_item_id'] = sku
                            name = transaction.Item.Title
                            if transaction.has_key('Variation'):
                                _v = transaction.Variation
                                if _v.has_key('SKU') and _v.SKU.isdigit() and ebay_item_obj.exists(cr, uid, int(_v.SKU), context=context):
                                    vals['ebay_item_variation_id'] = _v.SKU
                                name = _v.VariationTitle
                                vals['view_item_url'] = _v.VariationViewItemURL if _v.has_key('VariationViewItemURL') else ''
                                
                            vals['name'] = name
                            
                            ebay_sale_order_transaction_obj.create(cr, uid, vals, context=context)
                        
                page_number = page_number + 1

        return {
            'type': 'ir.actions.act_window',
            'name': 'Sale Orders',
            'view_mode': 'tree,form',
            'view_type': 'form',
            'res_model': 'ebay.sale.order',
            'context': "{'search_default_state': 'draft'}",
        }

get_order()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
