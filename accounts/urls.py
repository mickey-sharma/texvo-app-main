from django.urls import path
from . import views
from django.contrib.auth.views import LogoutView
from django.shortcuts import redirect
from django.contrib.auth import views as auth_views

def root_redirect(request):
    return redirect('accounts:login')

app_name = 'accounts'

urlpatterns = [
    path('', root_redirect, name='root'),
    path('login/', views.login_view, name='login'),
    path('logout/', LogoutView.as_view(next_page='accounts:login'), name='logout'),
    path('admin/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('manager/dashboard/', views.manager_dashboard, name='manager_dashboard'),
    path('client/dashboard/', views.client_dashboard, name='client_dashboard'),
    path('expert/dashboard/', views.expert_dashboard, name='expert_dashboard'),
    path('admin/users/', views.user_management, name='user_management'),
    path('admin/users/create/', views.user_create, name='user_create'),
    path('admin/users/<int:user_id>/view/', views.user_detail, name='user_detail'),
    path('admin/users/<int:user_id>/edit/', views.user_edit, name='user_edit'),
    path('admin/users/<int:user_id>/delete/', views.user_delete, name='user_delete'),
    path('admin/users/<int:user_id>/send-password/', views.send_password_reset, name='send_password_reset'),
    
    # Task management URLs
    path('admin/tasks/', views.task_management, name='task_management'),
    path('admin/tasks/create/', views.task_create, name='task_create'),
    path('admin/tasks/<int:task_id>/view/', views.task_detail, name='task_detail'),
    path('admin/tasks/<int:task_id>/edit/', views.task_edit, name='task_edit'),
    path('admin/tasks/<int:task_id>/delete/', views.task_delete, name='task_delete'),
    path('admin/attachments/<int:attachment_id>/delete/', views.delete_attachment, name='delete_attachment'),
      # Invoice Management URLs
    path('admin/invoices/', views.invoice_management, name='invoice_management'),
    path('admin/invoices/create/', views.create_invoice, name='create_invoice'),
    path('admin/api/available-tasks/', views.get_available_tasks, name='get_available_tasks'),
    path('admin/invoices/<int:invoice_id>/view/', views.invoice_detail, name='invoice_detail'),
    path('admin/invoices/<int:invoice_id>/payment/', views.update_payment, name='update_payment'),
    path('admin/invoices/<int:invoice_id>/delete/', views.delete_invoice, name='delete_invoice'),
    path('admin/invoices/<int:invoice_id>/resend/', views.resend_invoice, name='resend_invoice'),
    
    # Password reset URLs
    path('reset/<uidb64>/<token>/', 
         auth_views.PasswordResetConfirmView.as_view(
             template_name='accounts/password_reset_confirm.html',
             success_url='/accounts/login/'
         ), 
         name='password_reset_confirm'),
      # Calendar view URL
    path('admin/calendar/', views.calendar_simple, name='calendar_view'),
    path('admin/settings/', views.settings_view, name='settings'),
    # Add new payments page
    path('admin/payments/', views.expert_payments, name='expert_payments'),
]
