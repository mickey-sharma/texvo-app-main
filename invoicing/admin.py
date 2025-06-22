from django.contrib import admin
from .models import Invoice

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = [
        'invoice_number', 
        'task', 
        'get_amount_display',
        'get_paid_display', 
        'currency', 
        'payment_status', 
        'created_at'
    ]
    list_filter = ['payment_status', 'currency', 'created_at']
    search_fields = ['invoice_number', 'task__task_code', 'task__client__username']
    readonly_fields = ['created_at', 'updated_at', 'balance_due', 'is_fully_paid']
    
    fieldsets = (
        ('Invoice Details', {
            'fields': ('task', 'invoice_number', 'amount_due', 'currency')
        }),
        ('Payment Information', {
            'fields': ('amount_paid', 'payment_status', 'payment_date')
        }),
        ('Calculated Fields', {
            'fields': ('balance_due', 'is_fully_paid'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_amount_display(self, obj):
        return f"{obj.currency_symbol}{obj.amount_due:,.2f}"
    get_amount_display.short_description = 'Amount Due'
    
    def get_paid_display(self, obj):
        return f"{obj.currency_symbol}{obj.amount_paid:,.2f}"
    get_paid_display.short_description = 'Amount Paid'
    
    def save_model(self, request, obj, form, change):
        # Auto-update payment status based on payment amount
        if obj.amount_paid <= 0:
            obj.payment_status = 'Pending'
        elif obj.amount_paid >= obj.amount_due:
            obj.payment_status = 'Completed'
        else:
            obj.payment_status = 'Partial'
        
        super().save_model(request, obj, form, change)