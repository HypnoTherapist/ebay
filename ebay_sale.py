# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2010 Tiny SPRL (<http://tiny.be>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,

#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
from datetime import datetime, timedelta
from openerp.tools import DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT, DATETIME_FORMATS_MAP, float_compare
from openerp import pooler, tools
from dateutil.relativedelta import relativedelta
from openerp.osv import fields, osv
from openerp import netsvc
from openerp.tools.translate import _
import pytz
from openerp import SUPERUSER_ID

class sale_order(osv.osv):
    _inherit = "sale.order"
    
    _columns = {
        'ebay_sale_order_id': fields.many2one('ebay.sale.order', 'eBay User'),
    }

class ebay_sale_order(osv.osv):
    _name = "ebay.sale.order"
    _description = "eBay order"
    
    def _get_shipping_service_type(self, cr, uid, context=None):
        return self.pool.get('ebay.user').get_shipping_service_type()
    
    def _get_transaction_details(self, cr, uid, ids, name, args, context=None):
        result = dict.fromkeys(ids, False)
        for obj in self.browse(cr, uid, ids, context=context):
            if obj.transactions:
                details = ''
                for transaction in obj.transactions:
                    if details:
                        details += '\n'
                    details += '%s (x%d' % (transaction.name, transaction.quantity_purchased)
                result[obj.id] = details
        return result

    _columns = {
        'name': fields.char('Order Reference', size=64, required=True,
            readonly=True, states={'draft': [('readonly', False)], 'sent': [('readonly', False)]}, select=True),
        'currency': fields.char('Currency', size=3, readonly=True),
        'adjustment_amount': fields.float('Adjustment Amount', readonly=True),
        'amount_paid': fields.float('Amount Paid', readonly=True),
        'amount_saved': fields.float('Amount Saved', readonly=True),
        'buyer_checkout_message': fields.text('Message', readonly=True),
        'buyer_user_id': fields.char('User ID', readonly=True, states={'draft': [('readonly', False)]}),
        'cancel_reason': fields.selection([
            ('BuyerCancelOrder', 'BuyerCancelOrder'),
            ('BuyerNoShow', 'BuyerNoShow'),
            ('BuyerNotSchedule', 'BuyerNotSchedule'),
            ('BuyerRefused', 'BuyerRefused'),
            ('CustomCode', 'CustomCode'),
            ('OutOfStock', 'OutOfStock'),
            ('ValetDeliveryIssues', 'ValetDeliveryIssues'),
            ('ValetUnavailable', 'ValetUnavailable'),
            ], 'Cancel Reason', readonly=True),
        # CheckoutStatus
        'cs_last_modified_time': fields.datetime('Last Modified Time', readonly=True),
        'cs_ebay_payment_status': fields.selection([
            ('BuyerCreditCardFailed', 'BuyerCreditCardFailed'),
            ('BuyerECheckBounced', 'BuyerECheckBounced'),
            ('BuyerFailedPaymentReportedBySeller', 'BuyerFailedPaymentReportedBySeller'),
            ('CustomCode', 'CustomCode'),
            ('NoPaymentFailure', 'NoPaymentFailure'),
            ('PaymentInProcess', 'PaymentInProcess'),
            ('PayPalPaymentInProcess', 'PayPalPaymentInProcess'),
            ], 'Payment Status', readonly=True),
        'cs_payment_method': fields.char('Payment Method', readonly=True),
        'cs_status': fields.selection([
            ('Complete', 'Complete'),
            ('CustomCode', 'CustomCode'),
            ('Incomplete', 'Incomplete'),
            ('Pending', 'Pending'),
            ], 'Checkout Status', readonly=True, select=True),
        'created_time': fields.datetime('Created Time', readonly=True),
        'order_id': fields.char('Order ID', readonly=True),
        'order_status': fields.selection([
            ('Active', 'Active'),
            ('All', 'All'),
            ('Authenticated', 'Authenticated'),
            ('Cancelled', 'Cancelled'),
            ('Completed', 'Completed'),
            ('CustomCode', 'CustomCode'),
            ('Default', 'Default'),
            ('Inactive', 'Inactive'),
            ('InProcess', 'InProcess'),
            ('Invalid', 'Invalid'),
            ('Shipped', 'Shipped'),
            ], 'Order Status', readonly=True, select=True),
        'paid_time': fields.datetime('Paid Time', readonly=True),
        'payment_hold_status':  fields.selection([
            ('CustomCode', 'CustomCode'),
            ('MerchantHold', 'MerchantHold'),
            ('NewSellerHold', 'NewSellerHold'),
            ('None', 'None'),
            ('PaymentHold', 'PaymentHold'),
            ('PaymentReview', 'PaymentReview'),
            ('ReleaseConfirmed', 'ReleaseConfirmed'),
            ('Released', 'Released'),
            ('ReleasePending', 'ReleasePending'),
            ], 'Payment Hold Status', readonly=True),
        # ShippingDetails
        # SellingManagerSalesRecordNumber
        'sd_record_number': fields.integer('Record Number', readonly=True),
        'shipped_time': fields.datetime('Shipped Time', readonly=True),
        'subtotal': fields.float('Subtotal', readonly=True),
        'total': fields.float('Total', readonly=True),
        # TransactionArray
        'transactions': fields.one2many('ebay.sale.order.transaction', 'order_id', 'Transactions', readonly=True, states={'draft': [('readonly', False)]}),
        'partner_id': fields.many2one('res.partner', 'Customer', readonly=True, states={'draft': [('readonly', False)], 'sent': [('readonly', False)]}, required=True, change_default=True, select=True, track_visibility='always'),
        'ebay_user_id': fields.many2one('ebay.user', 'eBay User', states={'draft': [('readonly', False)], 'sent': [('readonly', False)]}, select=True, track_visibility='onchange'),
        'shipping_service': fields.selection(_get_shipping_service_type, 'Shipping service'),
        'state': fields.selection([
            ('draft', 'Draft'),
            ('confirmed', 'Waiting Availability'),
            ('assigned', 'Ready to Deliver'),
            ('sent', 'Delivered'),
            ('cancel', 'Cancelled'),
            ('pending', 'Pending'),
            ('done', 'Done'),
            ], 'Status', readonly=True, track_visibility='onchange',
            help="Gives the status of the quotation or sales order. \nThe 'Waiting Schedule' status is set when the invoice is confirmed but waiting for the scheduler to run on the order date.", select=True),
        'after_service_duration': fields.selection([
            ('0', '0 day'),
            ('7', '7 days'),
            ('15', '15 days'),
            ('25', '25 days'),
        ], 'Duration', readonly=True, help='After Service Duration'),
        'sale_order_ids': fields.one2many('sale.order', 'ebay_sale_order_id', 'Sale Orders', readonly=True),
        'transaction_details': fields.function(_get_transaction_details, type="text", method=True, string='Transaction Details'),
    }
    
    _defaults = {
        'name': lambda obj, cr, uid, context: '/',
        'created_time': fields.datetime.now(),
        'state': 'draft',
        'after_service_duration': 0,
    }
    
    _order = 'sd_record_number desc'
    
    def copy(self, cr, uid, id, default=None, context=None):
        if default is None:
            default = {}
        
        default.update({
            'order_id': '',
            'state': 'draft',
        })

        return super(ebay_sale_order, self).copy(cr, uid, id, default, context)
    
    def create(self, cr, uid, vals, context=None):
        if vals.get('name','/')=='/':
            sd_record_number = vals.get('sd_record_number',0) 
            if sd_record_number:
                vals['name'] = 'EOS/%s' % sd_record_number
        return super(ebay_sale_order, self).create(cr, uid, vals, context=context)
    
    def shipping_time(self, cr, uid, order, context=None):
        now_time = datetime.now()
        shipped_time = datetime.strptime(order.shipped_time, tools.DEFAULT_SERVER_DATETIME_FORMAT)
        daygenerator = (shipped_time + timedelta(x + 1) for x in xrange((now_time - shipped_time).days))
        return sum(1 for day in daygenerator if day.weekday() < 5)
    
    def _prepare_order(self, cr, uid, order, context=None):
        pricelist_id = self.pool.get('product.pricelist').search(cr, uid, [], context=context)[0]
        return {
            'client_order_ref': order.name,
            'date_order': order.created_time,
            'partner_id': order.partner_id.id,
            'partner_invoice_id': order.partner_id.id,
            'partner_shipping_id': order.partner_id.id,
            'pricelist_id': pricelist_id,
            'note': order.buyer_checkout_message,
            'ebay_sale_order_id': order.id,
        }
    
    def _prepare_order_line(self, cr, uid, order, line, sale_order_id, product, context=None):
        return {
            'order_id': sale_order_id,
            'name': line.name,
            'sequence': line.sd_record_number,
            'product_id': product.product_id.id,
            'price_unit': line.transaction_price,
            'type': 'make_to_order',
            'product_uom_qty': product.uos_coeff * line.quantity_purchased,
            'product_uos_qty': product.uos_coeff * line.quantity_purchased,
        }
    
    def _create_sale_order(self, cr, uid, order, context=None):
        if (order.state == 'draft' or order.state == 'pending') \
            and order.cs_ebay_payment_status == 'NoPaymentFailure' and order.cs_status == 'Complete':
            sale_order_obj = self.pool.get('sale.order')
            sale_order_line_obj = self.pool.get('sale.order.line')
            
            # check all line avaiable
            for line in order.transactions:
                if line.ebay_item_variation_id:
                    ebay_item_id = line.ebay_item_variation_id
                    product_ids = ebay_item_id.product_ids
                elif line.ebay_item_id:
                    ebay_item_id = line.ebay_item_id
                    product_ids = ebay_item_id.product_ids
                else:
                    return line.write(dict(state='exception'))
                
                if not ebay_item_id.exists() or not product_ids:
                    return line.write(dict(state='exception'))
                
                for product in product_ids:
                    if not product.product_id.exists():
                        return line.write(dict(state='exception'))
                    
            sale_order_id = sale_order_obj.create(cr, uid, self._prepare_order(cr, uid, order, context=context))
            for line in order.transactions:
                if line.ebay_item_variation_id:
                    ebay_item_id = line.ebay_item_variation_id
                    product_ids = ebay_item_id.product_ids
                elif line.ebay_item_id:
                    ebay_item_id = line.ebay_item_id
                    product_ids = ebay_item_id.product_ids
                
                for product in ebay_item_id.product_ids:
                    sale_order_line_obj.create(cr, uid, self._prepare_order_line(cr, uid, order, line, sale_order_id, product, context=context))
                line.write(dict(state='done'))
            sale_order_obj.action_button_confirm(cr, uid, [sale_order_id], context=context)
            order.write({'state': 'confirmed'})
    
    def action_confirm(self, cr, uid, ids, context=None):
        for order in self.browse(cr, uid, ids, context=context):
            self._create_sale_order(cr, uid, order, context=context)
        return True
    
    def action_assign(self, cr, uid, ids, context=None):
        stock_picking_obj = self.pool.get('stock.picking')
        for order in self.browse(cr, uid, ids, context=context):
            picking_ids = []
            for sale_order in order.sale_order_ids:
                if sale_order.state in ('progress', 'manual'):
                    picking_ids.extend([x.id for x in sale_order.picking_ids if x.state in ('confirmed', 'assigned')])
            
            if len(picking_ids) > 0:
                stock_picking_obj.action_assign(cr, uid, picking_ids)
                
            move_line_no_assigned = []
            picking_ids = [x.id for x in sale_order.picking_ids]
            for picking in stock_picking_obj.browse(cr, uid, picking_ids, context=context):
                move_line_no_assigned.extend([x.id for x in picking.move_lines if x.state not in ('assigned', 'done')])
            
            if len(move_line_no_assigned) == 0:
                order.write(dict(state='assigned'))
        return True
        
    def action_pending(self, cr, uid, ids, context=None):
        return self.write(cr, uid, ids, {'state': 'pending'}, context)
        
    def action_cancel(self, cr, uid, ids, context=None):
        return self.write(cr, uid, ids, {'state': 'cancel'}, context)
        
    def action_send(self, cr, uid, ids, context=None):
        sale_order_obj = self.pool.get('sale.order')
        stock_move_obj = self.pool.get('stock.move')
        ebay_ebay_obj = self.pool.get('ebay.ebay')
        send_ids = list()
        for order in self.browse(cr, uid, ids, context=context):
            user = order.ebay_user_id
            if order.state == 'assigned':
                for sale_order in order.sale_order_ids:
                    for picking in sale_order.picking_ids:
                        move_line_ids = [move_line.id for move_line in picking.move_lines if move_line.state not in ['done','cancel']]
                        stock_move_obj.action_done(cr, uid, move_line_ids, context=context)
                # complete sale
                call_data=dict(
                    FeedbackInfo=dict(
                        CommentText='Quick response and fast payment. Perfect! THANKS!!',
                        CommentType='Positive',
                        TargetUser=order.buyer_user_id,
                    ),
                    OrderID=order.order_id,
                    Shipped="true",
                )
                error_msg = 'Complete sale for the specified order %s' % order.name
                ebay_ebay_obj.call(cr, uid, user, 'CompleteSale', call_data, error_msg, context=context)
                send_ids.append(order.id)
        return self.write(cr, uid, send_ids, {'state': 'sent'}, context)
        
    def action_done(self, cr, uid, ids, context=None):
        done_ids = list()
        for order in self.browse(cr, uid, ids, context=context):
            if order.state == 'sent':
                done_ids.append(order.id)
        return self.write(cr, uid, done_ids, {'state': 'done'}, context)
    
    def action_open_message(self, cr, uid, ids, context=None):
        mod_obj = self.pool.get('ir.model.data')
        
        res = mod_obj.get_object_reference(cr, uid, 'ebay', 'view_ebay_sale_order_message_form')
        res_id = res and res[1] or False

        return {
            'name': _('Sale Orders Message'),
            'view_type': 'form',
            'view_mode': 'form',
            'view_id': [res_id],
            'res_model': 'ebay.sale.order',
            'type': 'ir.actions.act_window',
            'target': 'new',
            'res_id': ids and ids[0] or False,
        }
    
ebay_sale_order()

class ebay_sale_order_transaction(osv.osv):
    _name = "ebay.sale.order.transaction"
    _description = "eBay order transaction"
    
    def _get_variation(self, cr, uid, ids, field_name, arg, context):
        if context is None:
            context = {}
        res = {}
        for record in self.browse(cr, uid, ids, context=context):
            res[record.id] = record.ebay_item_id.variation
        return res
    
    _columns = {
        'name': fields.char('Description', required=True, readonly=True, states={'draft': [('readonly', False)]}),
        'actual_handling_cost': fields.float('Handling Cost'),
        'actual_shipping_cost': fields.float('Shipping Cost'),
        'created_date': fields.datetime('Created Date'),
        'final_value_fee': fields.float('Final Value Fee'),
        # Item
        'item_id': fields.char('Item ID', size=38, readonly=True),
        'order_line_item_id': fields.char('OrderLineItemID'),
        'quantity_purchased': fields.integer('Quantity'),
        'shipped_time': fields.datetime('Shipped Time'),
        # ShippingDetails
        # selling manager sales record number
        'sd_record_number': fields.integer('Record Number'),
        'transaction_id': fields.char('TransactionID'),
        'transaction_price': fields.float('Price'),
        'view_item_url': fields.char('View Item URL', readonly=True),
        
        'order_id': fields.many2one('ebay.sale.order', 'Order Reference', required=True, ondelete='cascade', select=True, readonly=True, states={'draft':[('readonly',False)]}),
        'ebay_item_id': fields.many2one('ebay.item', 'Item', change_default=True, ondelete='set null'),
        'ebay_item_variation_id': fields.many2one('ebay.item', 'Variation', domain="[('parent_id', '=', ebay_item_id)]", change_default=True, ondelete='set null'),
        'variation': fields.function(_get_variation, type='boolean', method=True, string='Variation'),
        'broken': fields.boolean('Broken'),
        'order_partner_id': fields.related('order_id', 'partner_id', type='many2one', relation='res.partner', store=True, string='Customer'),
        'ebay_user_id':fields.related('order_id', 'ebay_user_id', type='many2one', relation='ebay.user', store=True, string='eBay User'),
        'state': fields.selection([('draft', 'Draft'),('confirmed', 'Confirmed'),('cancel', 'Cancelled'),('exception', 'Exception'),('done', 'Done')], 'Status', required=True, readonly=True,
                help='* The \'Draft\' status is set when the related sales order in draft status. \
                    \n* The \'Confirmed\' status is set when the related sales order is confirmed. \
                    \n* The \'Exception\' status is set when the related sales order is set as exception. \
                    \n* The \'Done\' status is set when the sales order line has been picked. \
                    \n* The \'Cancelled\' status is set when a user cancel the sales order related.'),
    }
    
    _defaults = {
        'created_date': fields.datetime.now(),
        'quantity_purchased': 1,
        'state': 'draft'
    }
    
    _order = 'sd_record_number desc'
    
    def on_change_ebay_item_id(self, cr, uid, id, ebay_item_id, context=None):
        value = dict()
        item = self.pool.get('ebay.item').browse(cr, uid, ebay_item_id, context=context)
        value['name'] = item.name
        value['ebay_item_variation_id'] = False
        value['variation'] = item.variation
        value['transaction_price'] = item.start_price
        return {
            'value': value
        }
    
    def on_change_ebay_item_variation_id(self, cr, uid, id, ebay_item_id, ebay_item_variation_id, context=None):
        value = dict()
        item = self.pool.get('ebay.item').browse(cr, uid, [ebay_item_id, ebay_item_variation_id], context=context)
        value['name'] = '%s%s' % (item[0].name, item[1].name)
        value['transaction_price'] = item[1].start_price
        return {
            'value': value
        }
    
    def action_send_message(self, cr, uid, ids, context=None):
        if len(ids) == 0:
            return False
        id = ids[0]
        line = self.browse(cr, uid, id, context=context)
        ctx = dict(context)
        ctx.update({
            'default_model': 'ebay.message',
            'default_name': line.name,
            'default_recipient_or_sender_id': line.order_id.buyer_user_id,
            'default_item_id': line.item_id,
            'default_title': line.name,
            'default_current_price': line.transaction_price,
            'default_question_type': 'General',
            'default_last_modified_date': fields.datetime.now(),
            'default_ebay_user_id': line.ebay_user_id.id,
            'default_type': 'out',
            'default_partner_id': line.order_partner_id.id,
            'default_order_id': line.order_id.id
            })
        return {
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'ebay.message',
            'target': 'new',
            'context': ctx,
        }

ebay_sale_order_transaction()
