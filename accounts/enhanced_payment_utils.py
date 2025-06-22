# Enhanced payment calculation functions with Invoice currency field
import requests
from decimal import Decimal
from django.db.models import Sum, Q
from invoicing.models import Invoice

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

def calculate_enhanced_payments():
    """Calculate comprehensive payment metrics with currency conversion"""
    
    # Get live exchange rates
    exchange_rates = get_exchange_rates()
    
    # Initialize totals
    total_received_inr = 0
    completed_payments_inr = 0
    partial_payments_inr = 0
    total_pending_inr = 0
    
    received_count = 0
    pending_count = 0
    
    # Process all invoices with payments
    invoices_with_payments = Invoice.objects.filter(amount_paid__gt=0)
    
    for invoice in invoices_with_payments:
        # Convert paid amount to INR
        paid_amount_inr = invoice.get_paid_amount_in_inr(exchange_rates)
        total_received_inr += paid_amount_inr
        received_count += 1
        
        # Categorize as completed or partial
        if invoice.payment_status == 'Completed':
            completed_payments_inr += paid_amount_inr
        else:
            partial_payments_inr += paid_amount_inr
    
    # Calculate pending payments (unpaid balances)
    pending_invoices = Invoice.objects.exclude(payment_status='Completed')
    
    for invoice in pending_invoices:
        if invoice.balance_due > 0:
            # Convert balance to INR
            balance_inr = invoice.get_amount_in_inr(exchange_rates) - invoice.get_paid_amount_in_inr(exchange_rates)
            if balance_inr > 0:
                total_pending_inr += balance_inr
                pending_count += 1
    
    return {
        'total_payment_received': total_received_inr,
        'completed_payments_inr': completed_payments_inr,
        'partial_payments_inr': partial_payments_inr,
        'received_invoices_count': received_count,
        'total_payment_pending': total_pending_inr,
        'pending_invoices_count': pending_count,
        'exchange_rates': exchange_rates,
    }

# Add this to your admin_dashboard view in accounts/views.py:

def admin_dashboard(request):
    # ...existing code...
    
    # Replace existing payment calculations with enhanced version
    enhanced_payments = calculate_enhanced_payments()
    dashboard_data.update(enhanced_payments)
    
    # ...rest of existing code...
    
    return render(request, 'accounts/admin_dashboard.html', {
        'dashboard_data': dashboard_data,
        # ...other context...
    })