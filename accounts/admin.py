from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Invoice

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'is_staff', 'is_active')
    list_filter = ('role', 'is_staff', 'is_active')
    search_fields = ('username', 'email')
    
    fieldsets = UserAdmin.fieldsets + (
        ('Role Information', {'fields': ('role',)}),
    )
    
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Role Information', {'fields': ('role',)}),
    )

class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['invoice_number', 'task', 'amount_due', 'amount_paid', 'currency', 'payment_status', 'created_at']
    list_filter = ['payment_status', 'currency', 'created_at', 'payment_date']
    search_fields = ['invoice_number', 'task__task_code', 'task__client__username']
    readonly_fields = ['invoice_number', 'balance_due', 'created_at', 'updated_at']

admin.site.register(Invoice, InvoiceAdmin)
