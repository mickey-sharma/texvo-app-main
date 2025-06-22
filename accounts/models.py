from django.contrib.auth.models import AbstractUser
from django.db import models
import os

class User(AbstractUser):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('manager', 'Manager'),
        ('client', 'Client'),
        ('expert', 'Expert'),
    ]
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='client')
    
    def __str__(self):
        return f"{self.username} - {self.role}"

def task_attachment_upload_path(instance, filename):
    # Check if instance has task_code (for Task model) or task.task_code (for TaskAttachment model)
    if hasattr(instance, 'task_code'):
        task_code = instance.task_code
    elif hasattr(instance, 'task') and hasattr(instance.task, 'task_code'):
        task_code = instance.task.task_code
    else:
        task_code = 'unknown'
    
    # Upload to MEDIA_ROOT/tasks/task_code/filename
    return f'tasks/{task_code}/{filename}'

class Task(models.Model):
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('InProgress', 'In Progress'),
        ('Completed', 'Completed'),
        ('Failed', 'Failed'),
        ('Cancelled', 'Cancelled'),
    ]
    
    CURRENCY_CHOICES = [
        ('INR', '₹ INR'),
        ('USD', '$ USD'),
        ('EUR', '€ EUR'),
        ('GBP', '£ GBP'),
    ]
    
    # Basic Task Information
    task_code = models.CharField(max_length=20, unique=True, editable=False)
    client = models.ForeignKey(User, on_delete=models.CASCADE, related_name='client_tasks', limit_choices_to={'role': 'client'})
    module_code = models.CharField(max_length=50)
    module_name = models.CharField(max_length=200)
    word_count = models.PositiveIntegerField()
    additional_words = models.PositiveIntegerField(default=0)
    
    # Pricing and Timeline
    quoted_price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='INR')
    deadline = models.DateTimeField()
    allocation = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, limit_choices_to={'role': 'expert'}, related_name='expert_tasks')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    notes = models.TextField(blank=True, null=True)
    attachments = models.FileField(upload_to=task_attachment_upload_path, blank=True, null=True)
    
    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_tasks')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def save(self, *args, **kwargs):
        if not self.task_code:
            # Generate task code: TD2001, TD2002, etc.
            last_task = Task.objects.filter(task_code__startswith='TD').order_by('task_code').last()
            if last_task:
                last_number = int(last_task.task_code[2:])
                new_number = last_number + 1
            else:
                new_number = 2001
            self.task_code = f'TD{new_number}'
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.task_code} - {self.module_name}"
    
    @property
    def attachment_size(self):
        if self.attachments:
            return self.attachments.size
        return 0
    
    @property
    def attachment_name(self):
        if self.attachments:
            return os.path.basename(self.attachments.name)
        return None
    
    @property
    def currency_symbol(self):
        currency_symbols = {
            'INR': '₹',
            'USD': '$',
            'EUR': '€',
            'GBP': '£',
        }
        return currency_symbols.get(self.currency, '₹')
    
    @property
    def formatted_price(self):
        return f"{self.currency_symbol}{self.quoted_price}"

class TaskAttachment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='task_attachments')
    file = models.FileField(upload_to=task_attachment_upload_path)
    file_name = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField()
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['uploaded_at']
    
    def __str__(self):
        return f"{self.task.task_code} - {self.file_name}"
    
    @property
    def file_size_mb(self):
        return round(self.file_size / (1024 * 1024), 2)

def invoice_receipt_upload_path(instance, filename):
    # Upload to MEDIA_ROOT/invoices/invoice_number/receipts/filename
    return f'invoices/{instance.invoice_number}/receipts/{filename}'

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

    task = models.OneToOneField('Task', on_delete=models.CASCADE, related_name='invoice')
    invoice_number = models.CharField(max_length=20, unique=True)
    amount_due = models.DecimalField(max_digits=10, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(
        max_length=3, 
        choices=CURRENCY_CHOICES, 
        default='INR',
        help_text='Invoice currency'
    )
    due_date = models.DateTimeField(
        null=True, 
        blank=True,
        help_text='Payment due date'
    )
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='Pending')
    payment_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Invoice {self.invoice_number} - {self.task.task_code if self.task else 'No Task'}"    
    
    @property
    def payment_percentage(self):
        """Calculate payment percentage"""
        if self.amount_due > 0:
            return (self.amount_paid / self.amount_due) * 100
        return 0
    
    @property
    def balance_due(self):
        """Calculate remaining balance"""
        return self.amount_due - self.amount_paid
    
    @property
    def currency_symbol(self):
        """Get currency symbol based on currency code"""
        currency_symbols = {
            'USD': '$',
            'EUR': '€', 
            'GBP': '£',
            'INR': '₹',
        }
        return currency_symbols.get(self.currency, '₹')

    @property
    def is_fully_paid(self):
        """Check if invoice is fully paid"""
        return self.amount_paid >= self.amount_due

    @property
    def is_overdue(self):
        """Check if invoice is overdue"""
        if not self.due_date:
            return False
        from django.utils import timezone
        return self.due_date < timezone.now() and not self.is_fully_paid

    def get_amount_in_inr(self, exchange_rates=None):
        """Convert amount to INR using live exchange rates"""
        if self.currency == 'INR':
            return float(self.amount_due)
        
        if not exchange_rates:
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

    def save(self, *args, **kwargs):
        # Generate invoice number if not exists
        if not self.invoice_number:
            # Get current year and month
            from datetime import datetime
            now = datetime.now()
            year_month = now.strftime('%Y%m')
            
            # Get the last invoice number for this month
            last_invoice = Invoice.objects.filter(
                invoice_number__startswith=f'INV{year_month}'
            ).order_by('-invoice_number').first()
            
            if last_invoice:
                # Extract the sequence number and increment
                try:
                    last_sequence = int(last_invoice.invoice_number[-4:])
                    new_sequence = last_sequence + 1
                except (ValueError, IndexError):
                    new_sequence = 1
            else:
                # First invoice of the month
                new_sequence = 1
            
            # Generate new invoice number: INV202412001, INV202412002, etc.
            self.invoice_number = f'INV{year_month}{new_sequence:04d}'
        
        super().save(*args, **kwargs)

class ExpertPayRate(models.Model):
    """Model to track expert price per word rates"""
    expert = models.OneToOneField(User, on_delete=models.CASCADE, related_name='pay_rate', limit_choices_to={'role': 'expert'})
    price_per_word = models.DecimalField(max_digits=6, decimal_places=3, default=0.500)
    currency = models.CharField(max_length=3, choices=Invoice.CURRENCY_CHOICES, default='INR')
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.expert.username} - {self.currency} {self.price_per_word}/word"
