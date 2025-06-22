from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class Invoice(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Partial', 'Partial Payment'),
        ('Completed', 'Completed'),
        ('Overdue', 'Overdue'),
    ]
    
    CURRENCY_CHOICES = [
        ('INR', 'Indian Rupee (₹)'),
        ('USD', 'US Dollar ($)'),
        ('EUR', 'Euro (€)'),
        ('GBP', 'British Pound (£)'),
    ]

    # Use string reference to avoid import issues
    task = models.OneToOneField('accounts.Task', on_delete=models.CASCADE, related_name='invoice')
    invoice_number = models.CharField(max_length=20, unique=True)
    amount_due = models.DecimalField(max_digits=10, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(
        max_length=3, 
        choices=CURRENCY_CHOICES, 
        default='INR',
        help_text='Invoice currency'
    )
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='Pending')
    payment_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Invoice {self.invoice_number} - {self.task.task_code}"

    @property
    def balance_due(self):
        """Calculate remaining balance"""
        return self.amount_due - self.amount_paid

    @property
    def is_fully_paid(self):
        """Check if invoice is fully paid"""
        return self.amount_paid >= self.amount_due

    @property
    def currency_symbol(self):
        """Get currency symbol"""
        symbols = {
            'INR': '₹',
            'USD': '$',
            'EUR': '€',
            'GBP': '£'
        }
        return symbols.get(self.currency, '₹')

    def get_amount_in_inr(self, exchange_rates=None):
        """Convert amount to INR using live exchange rates"""
        if self.currency == 'INR':
            return float(self.amount_due)
        
        if not exchange_rates:
            # Import here to avoid circular imports
            try:
                from accounts.views import get_exchange_rates
                exchange_rates = get_exchange_rates()
            except:
                # Fallback rates
                exchange_rates = {
                    'USD_TO_INR': 82.0,
                    'EUR_TO_INR': 88.5,
                    'GBP_TO_INR': 101.2,
                }
        
        # Convert to INR
        if self.currency == 'USD':
            return float(self.amount_due) * exchange_rates.get('USD_TO_INR', 82.0)
        elif self.currency == 'EUR':
            return float(self.amount_due) * exchange_rates.get('EUR_TO_INR', 88.5)
        elif self.currency == 'GBP':
            return float(self.amount_due) * exchange_rates.get('GBP_TO_INR', 101.2)
        else:
            return float(self.amount_due)

    def get_paid_amount_in_inr(self, exchange_rates=None):
        """Convert paid amount to INR using live exchange rates"""
        if self.currency == 'INR':
            return float(self.amount_paid)
        
        if not exchange_rates:
            try:
                from accounts.views import get_exchange_rates
                exchange_rates = get_exchange_rates()
            except:
                exchange_rates = {
                    'USD_TO_INR': 82.0,
                    'EUR_TO_INR': 88.5,
                    'GBP_TO_INR': 101.2,
                }
        
        # Convert to INR
        if self.currency == 'USD':
            return float(self.amount_paid) * exchange_rates.get('USD_TO_INR', 82.0)
        elif self.currency == 'EUR':
            return float(self.amount_paid) * exchange_rates.get('EUR_TO_INR', 88.5)
        elif self.currency == 'GBP':
            return float(self.amount_paid) * exchange_rates.get('GBP_TO_INR', 101.2)
        else:
            return float(self.amount_paid)