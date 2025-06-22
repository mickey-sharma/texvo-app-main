import requests
from decimal import Decimal
import json

def get_exchange_rates():
    """Get live exchange rates for currency conversion"""
    try:
        # Using exchangerate-api.com (free tier)
        response = requests.get('https://api.exchangerate-api.com/v4/latest/USD', timeout=5)
        if response.status_code == 200:
            rates = response.json()['rates']
            return {
                'USD_TO_INR': rates.get('INR', 82.0),
                'EUR_TO_INR': rates.get('INR', 82.0) / rates.get('EUR', 0.85),
                'GBP_TO_INR': rates.get('INR', 82.0) / rates.get('GBP', 0.73),
                'last_updated': 'live'
            }
    except Exception as e:
        print(f"Exchange rate API error: {e}")
    
    # Fallback rates if API fails
    return {
        'USD_TO_INR': 82.0,
        'EUR_TO_INR': 88.5,
        'GBP_TO_INR': 101.2,
        'last_updated': 'fallback'
    }

def convert_to_inr(amount, currency, exchange_rates):
    """Convert amount to INR based on currency"""
    if not amount:
        return 0.0
    
    amount = float(amount)
    
    if currency == 'INR':
        return amount
    elif currency == 'USD':
        return amount * exchange_rates['USD_TO_INR']
    elif currency == 'EUR':
        return amount * exchange_rates['EUR_TO_INR']
    elif currency == 'GBP':
        return amount * exchange_rates['GBP_TO_INR']
    else:
        return amount  # Default to original amount

# Replace the payment calculation section in admin_dashboard function:
def enhanced_payment_calculation(dashboard_data):
    """Enhanced payment calculation with currency conversion and partial payments"""
    
    # Get live exchange rates
    exchange_rates = get_exchange_rates()
    
    # Calculate total payment received (all payments in INR)
    all_invoices = Invoice.objects.all()
    total_received_inr = 0
    total_partial_inr = 0
    completed_payments_inr = 0
    payment_count = 0
    
    for invoice in all_invoices:
        if invoice.amount_paid > 0:
            # Get currency from invoice (add default if field doesn't exist)
            invoice_currency = getattr(invoice, 'currency', 'INR')
            
            # Convert to INR based on invoice currency
            amount_in_inr = convert_to_inr(
                invoice.amount_paid, 
                invoice_currency, 
                exchange_rates
            )
            total_received_inr += amount_in_inr
            payment_count += 1
            
            # Categorize as complete or partial
            if invoice.payment_status == 'Completed':
                completed_payments_inr += amount_in_inr
            else:
                # This is a partial payment
                total_partial_inr += amount_in_inr
    
    # Calculate pending payments in INR
    total_pending_inr = 0
    pending_count = 0
    
    for invoice in all_invoices.exclude(payment_status='Completed'):
        balance = invoice.amount_due - invoice.amount_paid
        if balance > 0:
            invoice_currency = getattr(invoice, 'currency', 'INR')
            balance_inr = convert_to_inr(
                balance,
                invoice_currency,
                exchange_rates
            )
            total_pending_inr += balance_inr
            pending_count += 1
    
    # Update dashboard data
    dashboard_data.update({
        'total_payment_received': total_received_inr,
        'completed_payments_inr': completed_payments_inr,
        'partial_payments_inr': total_partial_inr,
        'received_invoices_count': payment_count,
        'total_payment_pending': total_pending_inr,
        'pending_invoices_count': pending_count,
        'exchange_rates': exchange_rates,
    })
    
    return dashboard_data

# Add this to your admin_dashboard function:
# ...existing code...

# Replace the existing payment calculation with:
dashboard_data = enhanced_payment_calculation(dashboard_data)

# ...rest of existing code...