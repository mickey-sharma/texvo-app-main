from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login
from django.contrib import messages
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from .models import User, Task, TaskAttachment, Invoice, ExpertPayRate
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_datetime
import json
import string
import secrets
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.hashers import check_password
import random
from django.db.models import Sum, Count, Case, When, IntegerField, F, DecimalField
from django.db.models.functions import TruncMonth, ExtractMonth, ExtractYear
import calendar

@csrf_protect
def login_view(request):
    if request.user.is_authenticated:
        return redirect_based_on_role(request.user)
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            return redirect_based_on_role(user)
        else:
            messages.error(request, 'Invalid username or password')
    
    return render(request, 'accounts/login.html')

def redirect_based_on_role(user):
    role_redirects = {
        'admin': '/accounts/admin/dashboard/',
        'manager': '/accounts/manager/dashboard/',
        'client': '/accounts/client/dashboard/',
        'expert': '/accounts/expert/dashboard/',
    }
    
    return redirect(role_redirects.get(user.role, '/accounts/dashboard/'))

@login_required
def dashboard_view(request):
    return render(request, 'accounts/dashboard.html', {'user': request.user})

# Dashboard views for different roles
@login_required
def admin_dashboard(request):
    if request.user.role != 'admin':
        return redirect('accounts:dashboard')
    
    from django.db.models import Sum, Count, Q
    from datetime import datetime, timedelta
    import json
    import requests
    from decimal import Decimal
    
    def get_exchange_rate(from_currency, to_currency='INR'):
        """Get live exchange rate from external API"""
        try:
            if from_currency == to_currency:
                return 1.0
            
            # Using exchangerate-api.com (free tier)
            url = f"https://api.exchangerate-api.com/v4/latest/{from_currency}"
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                return data['rates'].get(to_currency, 1.0)
            else:
                # Fallback rates if API fails
                fallback_rates = {
                    'USD': 83.0,  # USD to INR
                    'EUR': 90.0,  # EUR to INR  
                    'GBP': 105.0, # GBP to INR
                    'INR': 1.0
                }
                return fallback_rates.get(from_currency, 1.0)
        except Exception as e:
            print(f"Error fetching exchange rate for {from_currency}: {str(e)}")
            # Fallback rates
            fallback_rates = {
                'USD': 83.0,
                'EUR': 90.0,
                'GBP': 105.0,
                'INR': 1.0
            }
            return fallback_rates.get(from_currency, 1.0)
    
    # Get current date and time ranges
    today = timezone.now().date()
    tomorrow = today + timedelta(days=1)
    this_month_start = today.replace(day=1)
    next_month = (this_month_start + timedelta(days=32)).replace(day=1)
    this_week_start = today - timedelta(days=today.weekday())
    
    # Calculate dashboard metrics
    dashboard_data = {}
    
    # Total words in ongoing tasks
    ongoing_tasks = Task.objects.filter(status='InProgress')
    dashboard_data['total_words_ongoing'] = ongoing_tasks.aggregate(
        total=Sum('word_count')
    )['total'] or 0
    dashboard_data['ongoing_tasks_count'] = ongoing_tasks.count()
    
    # Total words for tasks due tomorrow
    tomorrow_tasks = Task.objects.filter(deadline__date=tomorrow)
    dashboard_data['total_words_task_due'] = tomorrow_tasks.aggregate(
        total=Sum('word_count')
    )['total'] or 0
    dashboard_data['tomorrow_tasks_count'] = tomorrow_tasks.count()
    
    # Total payments received today (converted to INR)
    today_payments = Invoice.objects.filter(
        payment_date__date=today,
        payment_status='Completed'
    )
    total_payments_today_inr = 0
    for payment in today_payments:
        exchange_rate = get_exchange_rate(payment.currency, 'INR')
        amount_inr = float(payment.amount_paid) * exchange_rate
        total_payments_today_inr += amount_inr
    
    dashboard_data['total_payments_today'] = total_payments_today_inr
    dashboard_data['today_payments_count'] = today_payments.count()
    
    # Total payment received and pending with currency conversion
    all_invoices = Invoice.objects.all()
    
    # Calculate total payments received in INR
    total_payment_received_inr = 0
    completed_payments_inr = 0
    partial_payments_inr = 0
    
    for invoice in all_invoices:
        if invoice.amount_paid > 0:
            # Get exchange rate for invoice currency to INR
            exchange_rate = get_exchange_rate(invoice.currency, 'INR')
            amount_paid_inr = float(invoice.amount_paid) * exchange_rate
            total_payment_received_inr += amount_paid_inr
              # Categorize as complete or partial payment
            if invoice.amount_paid >= invoice.amount_due:
                completed_payments_inr += amount_paid_inr
            else:
                partial_payments_inr += amount_paid_inr
    
    dashboard_data['total_payment_received'] = total_payment_received_inr
    dashboard_data['completed_payments_inr'] = completed_payments_inr
    dashboard_data['partial_payments_inr'] = partial_payments_inr
    
    # Currency-wise payment breakdown
    currency_breakdown = {}
    for currency_code, currency_name in Invoice.CURRENCY_CHOICES:
        invoices_by_currency = all_invoices.filter(currency=currency_code)
        
        total_paid_in_currency = 0
        total_due_in_currency = 0
        completed_count = 0
        pending_count = 0
        
        for invoice in invoices_by_currency:
            total_paid_in_currency += float(invoice.amount_paid)
            total_due_in_currency += float(invoice.amount_due)
            
            if invoice.payment_status == 'Completed':
                completed_count += 1
            else:
                pending_count += 1
        
        if total_paid_in_currency > 0 or total_due_in_currency > 0:
            # Convert to INR for comparison
            exchange_rate = get_exchange_rate(currency_code, 'INR')
            
            currency_breakdown[currency_code] = {
                'currency_name': currency_name,
                'symbol': {'USD': '$', 'EUR': '€', 'GBP': '£', 'INR': '₹'}.get(currency_code, '₹'),
                'total_paid': total_paid_in_currency,
                'total_due': total_due_in_currency,
                'total_paid_inr': total_paid_in_currency * exchange_rate,
                'total_due_inr': total_due_in_currency * exchange_rate,
                'pending_amount': total_due_in_currency - total_paid_in_currency,
                'pending_amount_inr': (total_due_in_currency - total_paid_in_currency) * exchange_rate,
                'completed_count': completed_count,
                'pending_count': pending_count,
                'payment_percentage': (total_paid_in_currency / total_due_in_currency * 100) if total_due_in_currency > 0 else 0
            }
    
    dashboard_data['currency_breakdown'] = currency_breakdown

    # Calculate total pending amount (simple loop method)
    pending_invoices = all_invoices.exclude(payment_status='Completed')
    total_pending = 0
    for invoice in pending_invoices:
        balance = invoice.amount_due - invoice.amount_paid
        if balance > 0:
            # Convert balance to INR
            exchange_rate = get_exchange_rate(invoice.currency, 'INR')
            balance_inr = float(balance) * exchange_rate
            total_pending += balance_inr
    
    dashboard_data['total_payment_pending'] = total_pending
    dashboard_data['received_invoices_count'] = all_invoices.filter(payment_status='Completed').count()
    dashboard_data['pending_invoices_count'] = pending_invoices.count()
    
    # Total words this month
    this_month_tasks = Task.objects.filter(created_at__date__range=[this_month_start, today])
    dashboard_data['total_words_this_month'] = this_month_tasks.aggregate(
        total=Sum('word_count')
    )['total'] or 0
    dashboard_data['this_month_tasks_count'] = this_month_tasks.count()
      # Payment chart data (last 7 days)
    payment_chart_data = []
    for i in range(6, -1, -1):
        date = today - timedelta(days=i)
        daily_payments = Invoice.objects.filter(
            payment_date__date=date,
            payment_status='Completed'
        )
        
        daily_total_inr = 0
        for payment in daily_payments:
            exchange_rate = get_exchange_rate(payment.currency, 'INR')
            amount_inr = float(payment.amount_paid) * exchange_rate
            daily_total_inr += amount_inr
        
        payment_chart_data.append({
            'date': date.strftime('%m/%d'),
            'amount': daily_total_inr
        })
      # Word count chart data (last 7 days)
    word_chart_data = []
    for i in range(6, -1, -1):
        date = today - timedelta(days=i)
        daily_words = Task.objects.filter(
            created_at__date=date
        ).aggregate(total=Sum('word_count'))['total'] or 0
        word_chart_data.append({
            'date': date.strftime('%m/%d'),
            'words': daily_words
        })
    
    # Expert upcoming payments (next 7 days)
    upcoming_deadline = today + timedelta(days=7)
    expert_payments = []    
    experts = User.objects.filter(role='expert', is_active=True)
    for expert in experts:
        upcoming_tasks = Task.objects.filter(
            allocation=expert,
            deadline__date__range=[today, upcoming_deadline],
            status__in=['InProgress', 'Pending']
        )
        
        total_amount = 0
        task_count = 0
        
        for task in upcoming_tasks:
            if hasattr(task, 'invoice'):
                balance = task.invoice.amount_due - task.invoice.amount_paid
                if balance > 0:
                    # Convert balance to INR
                    exchange_rate = get_exchange_rate(task.invoice.currency, 'INR')
                    balance_inr = float(balance) * exchange_rate
                    total_amount += balance_inr
                    task_count += 1
        
        if total_amount > 0:
            expert_payments.append({
                'expert_name': f"{expert.first_name} {expert.last_name}".strip() or expert.username,
                'amount': total_amount,
                'task_count': task_count
            })
    
    # Sort by amount descending
    expert_payments = sorted(expert_payments, key=lambda x: x['amount'], reverse=True)[:5]
    
    # Upcoming tasks for mini calendar (next 7 days)
    upcoming_tasks = Task.objects.filter(
        deadline__date__range=[today, upcoming_deadline]
    ).select_related('client', 'allocation').order_by('deadline')[:10]
    
    calendar_tasks = []
    for task in upcoming_tasks:
        calendar_tasks.append({
            'task_code': task.task_code,
            'client_name': f"{task.client.first_name} {task.client.last_name}".strip() or task.client.username,
            'deadline': task.deadline.strftime('%Y-%m-%d'),
            'deadline_formatted': task.deadline.strftime('%b %d'),
            'status': task.status,
            'allocation': task.allocation.username if task.allocation else 'Unassigned'
        })
    
    # Recent activity (last 10 actions)
    recent_tasks = Task.objects.filter(
        created_at__date__gte=this_week_start
    ).select_related('client', 'created_by').order_by('-created_at')[:5]
    
    recent_payments = Invoice.objects.filter(
        payment_date__date__gte=this_week_start
    ).select_related('task', 'task__client').order_by('-payment_date')[:5]
    
    # System statistics
    system_stats = {
        'total_users': User.objects.count(),
        'total_clients': User.objects.filter(role='client').count(),
        'total_experts': User.objects.filter(role='expert').count(),
        'total_tasks': Task.objects.count(),
        'completed_tasks': Task.objects.filter(status='Completed').count(),
        'total_invoices': Invoice.objects.count(),
        'paid_invoices': Invoice.objects.filter(payment_status='Completed').count(),
    }
    
    # Task status distribution
    status_distribution = {
        'pending': Task.objects.filter(status='Pending').count(),
        'in_progress': Task.objects.filter(status='InProgress').count(),
        'completed': Task.objects.filter(status='Completed').count(),
    }
    
    context = {
        'user': request.user,
        'dashboard_data': dashboard_data,
        'payment_chart_data': json.dumps(payment_chart_data),
        'word_chart_data': json.dumps(word_chart_data),
        'expert_payments': expert_payments,
        'calendar_tasks': calendar_tasks,
        'recent_tasks': recent_tasks,
        'recent_payments': recent_payments,
        'system_stats': system_stats,
        'status_distribution': json.dumps(status_distribution),
        'today': today.strftime('%Y-%m-%d'),
    }
    
    return render(request, 'accounts/admin_dashboard.html', context)

@login_required
def manager_dashboard(request):
    if request.user.role != 'manager':
        return redirect('accounts:dashboard')
    return render(request, 'accounts/manager_dashboard.html', {'user': request.user})

@login_required
def client_dashboard(request):
    if request.user.role != 'client':
        return redirect('accounts:dashboard')
    return render(request, 'accounts/client_dashboard.html', {'user': request.user})

@login_required
def expert_dashboard(request):
    if request.user.role != 'expert':
        return redirect('accounts:dashboard')
    return render(request, 'accounts/expert_dashboard.html', {'user': request.user})

@login_required
def user_management(request):
    if request.user.role != 'admin':
        return redirect('accounts:dashboard')
    
    # Get search query
    search_query = request.GET.get('search', '')
    role_filter = request.GET.get('role', '')
    status_filter = request.GET.get('status', '')
    
    # Start with all users
    users = User.objects.all()
    
    # Apply search filter
    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query)
        )
    
    # Apply role filter
    if role_filter:
        users = users.filter(role=role_filter)
    
    # Apply status filter
    if status_filter == 'active':
        users = users.filter(is_active=True)
    elif status_filter == 'inactive':
        users = users.filter(is_active=False)
    
    # Order by date joined (newest first)
    users = users.order_by('-date_joined')
    
    # Pagination
    paginator = Paginator(users, 10)  # Show 10 users per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get role choices for filter dropdown
    role_choices = User.ROLE_CHOICES
    
    context = {
        'users': page_obj,
        'search_query': search_query,
        'role_filter': role_filter,
        'status_filter': status_filter,
        'role_choices': role_choices,
        'total_users': users.count(),
    }
    
    return render(request, 'accounts/user_management.html', context)

@login_required
def user_detail(request, user_id):
    if request.user.role != 'admin':
        return redirect('accounts:dashboard')
    
    user_obj = get_object_or_404(User, id=user_id)
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Return JSON for AJAX requests
        data = {
            'id': user_obj.id,
            'username': user_obj.username,
            'email': user_obj.email,
            'first_name': user_obj.first_name,
            'last_name': user_obj.last_name,
            'role': user_obj.get_role_display(),
            'is_active': user_obj.is_active,
            'is_staff': user_obj.is_staff,
            'is_superuser': user_obj.is_superuser,
            'date_joined': user_obj.date_joined.strftime('%B %d, %Y at %I:%M %p'),
            'last_login': user_obj.last_login.strftime('%B %d, %Y at %I:%M %p') if user_obj.last_login else 'Never',
        }
        return JsonResponse(data)
    
    return render(request, 'accounts/user_detail.html', {'user_obj': user_obj})

@login_required
def user_edit(request, user_id):
    if request.user.role != 'admin':
        return redirect('accounts:dashboard')
    
    user_obj = get_object_or_404(User, id=user_id)
    
    if request.method == 'POST':
        # Update user data
        user_obj.username = request.POST.get('username', user_obj.username)
        user_obj.email = request.POST.get('email', user_obj.email)
        user_obj.first_name = request.POST.get('first_name', user_obj.first_name)
        user_obj.last_name = request.POST.get('last_name', user_obj.last_name)
        user_obj.role = request.POST.get('role', user_obj.role)
        user_obj.is_active = request.POST.get('is_active') == 'on'
        user_obj.is_staff = request.POST.get('is_staff') == 'on'
        
        try:
            user_obj.save()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': 'User updated successfully'})
            messages.success(request, 'User updated successfully')
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': str(e)})
            messages.error(request, f'Error updating user: {str(e)}')
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        data = {
            'id': user_obj.id,
            'username': user_obj.username,
            'email': user_obj.email,
            'first_name': user_obj.first_name,
            'last_name': user_obj.last_name,
            'role': user_obj.role,
            'is_active': user_obj.is_active,
            'is_staff': user_obj.is_staff,
            'role_choices': User.ROLE_CHOICES,
        }
        return JsonResponse(data)
    
    return redirect('accounts:user_management')

@login_required
@require_POST
def user_delete(request, user_id):
    if request.user.role != 'admin':
        return JsonResponse({'success': False, 'message': 'Unauthorized'})
    
    user_obj = get_object_or_404(User, id=user_id)
    
    # Prevent self-deletion
    if user_obj.id == request.user.id:
        return JsonResponse({'success': False, 'message': 'You cannot delete your own account'})
    
    try:
        username = user_obj.username
        user_obj.delete()
        return JsonResponse({'success': True, 'message': f'User {username} deleted successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})

@login_required
def user_create(request):
    if request.user.role != 'admin':
        return redirect('accounts:dashboard')
    
    if request.method == 'POST':
        try:
            # Create new user
            username = request.POST.get('username')
            email = request.POST.get('email')
            first_name = request.POST.get('first_name')
            last_name = request.POST.get('last_name')
            role = request.POST.get('role')
            is_active = request.POST.get('is_active') == 'on'
            is_staff = request.POST.get('is_staff') == 'on'
            
            # Check if username already exists
            if User.objects.filter(username=username).exists():
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'message': 'Username already exists'})
                messages.error(request, 'Username already exists')
                return redirect('accounts:user_management')
            
            # Create user without password
            user_obj = User.objects.create_user(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                password=User.objects.make_random_password(),  # Temporary random password
                is_active=is_active,
                is_staff=is_staff
            )
            user_obj.role = role
            user_obj.set_unusable_password()  # Make password unusable
            user_obj.save()
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': f'User {username} created successfully'})
            messages.success(request, f'User {username} created successfully')
            
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': str(e)})
            messages.error(request, f'Error creating user: {str(e)}')
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        data = {
            'role_choices': User.ROLE_CHOICES,
        }
        return JsonResponse(data)
    
    return redirect('accounts:user_management')

@login_required
@require_POST
def send_password_reset(request, user_id):
    if request.user.role != 'admin':
        return JsonResponse({'success': False, 'message': 'Unauthorized'})
    
    user_obj = get_object_or_404(User, id=user_id)
    
    if not user_obj.email:
        return JsonResponse({'success': False, 'message': 'User has no email address'})
    
    try:
        # Generate password reset token
        token = default_token_generator.make_token(user_obj)
        uid = urlsafe_base64_encode(force_bytes(user_obj.pk))
        
        # Create reset link
        reset_link = request.build_absolute_uri(f'/accounts/reset/{uid}/{token}/')
        
        # Send styled email with reset link
        subject = 'Reset Your Texvo Account Password'
        
        html_message = f'''
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    margin: 0;
                    padding: 0;
                    font-family: 'Arial', sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                }}
                .email-container {{
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .email-card {{
                    background: rgba(255, 255, 255, 0.95);
                    backdrop-filter: blur(20px);
                    border-radius: 20px;
                    padding: 40px;
                    box-shadow: 0 25px 45px rgba(0, 0, 0, 0.1);
                    border: 1px solid rgba(255, 255, 255, 0.2);
                }}
                .header {{
                    text-align: center;
                    margin-bottom: 30px;
                }}
                .logo {{
                    font-size: 2.5rem;
                    font-weight: bold;
                    letter-spacing: 3px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    background-clip: text;
                    margin-bottom: 10px;
                }}
                .subtitle {{
                    color: #666;
                    font-size: 1.1rem;
                }}
                .content {{
                    color: #333;
                    line-height: 1.6;
                    margin-bottom: 30px;
                }}
                .greeting {{
                    font-size: 1.2rem;
                    font-weight: 600;
                    color: #333;
                    margin-bottom: 20px;
                }}
                .message {{
                    font-size: 1rem;
                    margin-bottom: 25px;
                }}
                .reset-button {{
                    display: inline-block;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    text-decoration: none;
                    padding: 15px 30px;
                    border-radius: 10px;
                    font-weight: 600;
                    font-size: 1.1rem;
                    transition: all 0.3s ease;
                    box-shadow: 0 10px 20px rgba(0, 0, 0, 0.1);
                }}
                .reset-button:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 15px 30px rgba(0, 0, 0, 0.2);
                }}
                .link-info {{
                    background: #f8f9fa;
                    border-left: 4px solid #667eea;
                    padding: 15px;
                    border-radius: 8px;
                    margin: 25px 0;
                }}
                .link-info p {{
                    margin: 0;
                    color: #666;
                    font-size: 0.9rem;
                }}
                .footer {{
                    margin-top: 40px;
                    padding-top: 20px;
                    border-top: 1px solid #eee;
                    text-align: center;
                    color: #999;
                    font-size: 0.9rem;
                }}
                .security-note {{
                    background: rgba(255, 193, 7, 0.1);
                    border: 1px solid rgba(255, 193, 7, 0.3);
                    border-radius: 8px;
                    padding: 15px;
                    margin: 20px 0;
                }}
                .security-note p {{
                    margin: 0;
                    color: #856404;
                    font-size: 0.9rem;
                }}
                @media (max-width: 600px) {{
                    .email-card {{
                        padding: 20px;
                        margin: 10px;
                    }}
                    .logo {{
                        font-size: 2rem;
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="email-container">
                <div class="email-card">
                    <div class="header">
                        <div class="logo">TEXVO</div>
                        <div class="subtitle">Password Reset Request</div>
                    </div>
                    
                    <div class="content">
                        <div class="greeting">Hello {user_obj.first_name or user_obj.username},</div>
                        
                        <div class="message">
                            A password reset has been requested for your Texvo account by an administrator. 
                            Click the button below to set up a new password for your account.
                        </div>
                        
                        <div style="text-align: center; margin: 30px 0;">
                            <a href="{reset_link}" class="reset-button">Reset Password</a>
                        </div>
                        
                        <div class="link-info">
                            <p><strong>Can't click the button?</strong> Copy and paste this link into your browser:</p>
                            <p style="word-break: break-all; margin-top: 10px;">{reset_link}</p>
                        </div>
                        
                        <div class="security-note">
                            <p><strong>Security Notice:</strong> This link will expire in 24 hours for your security. 
                            If you didn't request this password reset, please ignore this email.</p>
                        </div>
                        
                        <div class="message">
                            Your account details:
                            <br><strong>Username:</strong> {user_obj.username}
                            <br><strong>Email:</strong> {user_obj.email}
                        </div>
                    </div>
                    
                    <div class="footer">
                        <p>Best regards,<br>The Texvo Team</p>
                        <p style="margin-top: 15px;">
                            This is an automated message. Please do not reply to this email.
                        </p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        '''
        
        # Plain text version
        plain_message = f'''
Hello {user_obj.first_name or user_obj.username},

A password reset has been requested for your Texvo account by an administrator.

Please click the following link to reset your password:
{reset_link}

Your account details:
Username: {user_obj.username}
Email: {user_obj.email}

This link will expire in 24 hours for your security.
If you didn't request this password reset, please ignore this email.

Best regards,
The Texvo Team
        '''
        
        send_mail(
            subject,
            plain_message,
            settings.EMAIL_HOST_USER,
            [user_obj.email],
            fail_silently=False,
            html_message=html_message,
        )
        
        return JsonResponse({
            'success': True, 
            'message': f'Password reset link sent to {user_obj.email} successfully'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Error sending email: {str(e)}'})

@login_required
def task_management(request):
    if request.user.role not in ['admin', 'manager']:
        return redirect('accounts:dashboard')
    
    # Get search query and filters
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    allocation_filter = request.GET.get('allocation', '')
    
    # Start with all tasks
    tasks = Task.objects.all().select_related('allocation', 'created_by', 'client')
    
    # Apply search filter
    if search_query:
        tasks = tasks.filter(
            Q(task_code__icontains=search_query) |
            Q(module_code__icontains=search_query) |
            Q(module_name__icontains=search_query) |
            Q(notes__icontains=search_query) |
            Q(client__username__icontains=search_query)
        )
    
    # Apply status filter
    if status_filter:
        tasks = tasks.filter(status=status_filter)
    
    # Apply allocation filter
    if allocation_filter:
        if allocation_filter == 'unassigned':
            tasks = tasks.filter(allocation__isnull=True)
        else:
            tasks = tasks.filter(allocation_id=allocation_filter)
    
    # Order by created date (newest first)
    tasks = tasks.order_by('-created_at')
      # Pagination
    paginator = Paginator(tasks, 10)  # Show 10 tasks per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get experts and clients for dropdowns
    experts = User.objects.filter(role='expert', is_active=True)
    clients = User.objects.filter(role='client', is_active=True)
    
    context = {
        'tasks': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
        'allocation_filter': allocation_filter,
        'status_choices': Task.STATUS_CHOICES,
        'currency_choices': Task.CURRENCY_CHOICES,
        'experts': experts,
        'clients': clients,
        'total_tasks': tasks.count(),
    }
    
    return render(request, 'accounts/task_management.html', context)

@login_required
def task_create(request):
    if request.user.role not in ['admin', 'manager']:
        return redirect('accounts:dashboard')
    
    if request.method == 'POST':
        try:
            # Create new task
            client_id = request.POST.get('client')
            module_code = request.POST.get('module_code')
            module_name = request.POST.get('module_name')
            word_count = int(request.POST.get('word_count', 0))
            additional_words = int(request.POST.get('additional_words', 0))
            deadline_str = request.POST.get('deadline')
            quoted_price = float(request.POST.get('quoted_price', 0))
            currency = request.POST.get('currency', 'INR')
            allocation_id = request.POST.get('allocation')
            status = request.POST.get('status', 'Pending')
            notes = request.POST.get('notes', '')
            
            # Parse and handle timezone for deadline
            if deadline_str:
                deadline = parse_datetime(deadline_str)
                if deadline and timezone.is_naive(deadline):
                    deadline = timezone.make_aware(deadline)
            else:
                deadline = timezone.now()
            
            # Validate client selection
            if not client_id:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'message': 'Client selection is required'})
                messages.error(request, 'Client selection is required')
                return redirect('accounts:task_management')
            
            try:
                client = User.objects.get(id=client_id, role='client')
            except User.DoesNotExist:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'message': 'Invalid client selected'})
                messages.error(request, 'Invalid client selected')
                return redirect('accounts:task_management')
            
            allocation = None
            if allocation_id:
                try:
                    allocation = User.objects.get(id=allocation_id, role='expert')
                except User.DoesNotExist:
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({'success': False, 'message': 'Invalid expert selected'})
                    messages.error(request, 'Invalid expert selected')
                    return redirect('accounts:task_management')
            
            # Handle multiple file uploads
            files = request.FILES.getlist('attachments')
            total_size = 0
            
            for file in files:
                if file.size > 25 * 1024 * 1024:  # 25MB limit per file
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({'success': False, 'message': f'File {file.name} exceeds 25MB limit'})
                    messages.error(request, f'File {file.name} exceeds 25MB limit')
                    return redirect('accounts:task_management')
                
                total_size += file.size
            
            # Check total size limit (100MB for all files combined)
            if total_size > 100 * 1024 * 1024:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'message': 'Total file size exceeds 100MB limit'})
                messages.error(request, 'Total file size exceeds 100MB limit')
                return redirect('accounts:task_management')
            
            task = Task.objects.create(
                client=client,
                module_code=module_code,
                module_name=module_name,
                word_count=word_count,
                additional_words=additional_words,
                deadline=deadline,
                quoted_price=quoted_price,
                currency=currency,
                allocation=allocation,
                status='InProgress' if allocation else status,
                notes=notes,
                created_by=request.user
            )
            
            # Save multiple attachments
            for file in files:
                TaskAttachment.objects.create(
                    task=task,
                    file=file,
                    file_name=file.name,
                    file_size=file.size
                )
            
            # Send email to expert if allocated during creation
            if allocation:
                send_expert_allocation_email(request, task, allocation)
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': f'Task {task.task_code} created successfully'})
            messages.success(request, f'Task {task.task_code} created successfully')
            
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': f'Error creating task: {str(e)}'})
            messages.error(request, f'Error creating task: {str(e)}')
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        experts = User.objects.filter(role='expert', is_active=True)
        clients = User.objects.filter(role='client', is_active=True)
        data = {
            'status_choices': Task.STATUS_CHOICES,
            'experts': [{'id': expert.id, 'username': expert.username, 'name': f"{expert.first_name} {expert.last_name}"} for expert in experts],
            'clients': [{'id': client.id, 'username': client.username, 'name': f"{client.first_name} {client.last_name}"} for client in clients],
        }
        return JsonResponse(data)
    
    return redirect('accounts:task_management')

@login_required
def task_detail(request, task_id):
    if request.user.role not in ['admin', 'manager']:
        return redirect('accounts:dashboard')
    
    task = get_object_or_404(Task, id=task_id)
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Get all attachments for this task
        attachments = task.task_attachments.all()
        attachment_data = []
        
        for attachment in attachments:
            attachment_data.append({
                'id': attachment.id,
                'file_name': attachment.file_name,
                'file_size': attachment.file_size,
                'file_size_mb': attachment.file_size_mb,
                'file_url': attachment.file.url,
                'uploaded_at': attachment.uploaded_at.strftime('%B %d, %Y at %I:%M %p')
            })
        
        data = {
            'id': task.id,
            'task_code': task.task_code,
            'client': task.client.username,
            'client_name': f"{task.client.first_name} {task.client.last_name}",
            'module_code': task.module_code,
            'module_name': task.module_name,
            'word_count': task.word_count,
            'additional_words': task.additional_words,
            'deadline': task.deadline.strftime('%Y-%m-%d %H:%M'),
            'quoted_price': str(task.quoted_price),
            'currency': task.get_currency_display(),
            'formatted_price': task.formatted_price,
            'allocation': task.allocation.username if task.allocation else 'Unassigned',
            'allocation_name': f"{task.allocation.first_name} {task.allocation.last_name}" if task.allocation else 'Unassigned',
            'status': task.get_status_display(),
            'notes': task.notes or '',
            'attachments': attachment_data,
            'attachment_count': len(attachment_data),
            'created_by': task.created_by.username,
            'created_at': task.created_at.strftime('%B %d, %Y at %I:%M %p'),
            'updated_at': task.updated_at.strftime('%B %d, %Y at %I:%M %p'),
        }
        return JsonResponse(data)
    
    return render(request, 'accounts/task_detail.html', {'task': task})

@login_required
def task_edit(request, task_id):
    if request.user.role not in ['admin', 'manager']:
        return redirect('accounts:dashboard')
    
    task = get_object_or_404(Task, id=task_id)
    
    if request.method == 'POST':
        try:
            # Get old allocation for comparison
            old_allocation = task.allocation
            
            # Check if this is a quick allocation (only allocation field sent)
            allocation_id = request.POST.get('allocation')
            is_quick_allocation = allocation_id and len(request.POST) <= 3  # allocation, status, csrfmiddlewaretoken
            
            if is_quick_allocation:
                # Quick allocation - only update allocation and status
                if allocation_id:
                    task.allocation = User.objects.get(id=allocation_id, role='expert')
                    task.status = 'InProgress'  # Set status to InProgress when allocated
                else:
                    task.allocation = None
            else:
                # Full update - update all fields
                task.module_code = request.POST.get('module_code', task.module_code)
                task.module_name = request.POST.get('module_name', task.module_name)
                task.word_count = int(request.POST.get('word_count', task.word_count))
                task.additional_words = int(request.POST.get('additional_words', task.additional_words))
                task.quoted_price = float(request.POST.get('quoted_price', task.quoted_price))
                task.currency = request.POST.get('currency', task.currency)
            
            deadline_str = request.POST.get('deadline')
            if deadline_str:
                deadline = parse_datetime(deadline_str)
                if deadline and timezone.is_naive(deadline):
                    deadline = timezone.make_aware(deadline)
                task.deadline = deadline
            
            task.status = request.POST.get('status', task.status)
            task.notes = request.POST.get('notes', task.notes)
            
            if allocation_id:
                task.allocation = User.objects.get(id=allocation_id, role='expert')
                # If newly allocated (different expert or previously unassigned)
                if old_allocation != task.allocation:
                    task.status = 'InProgress'  # Set status to InProgress when allocated
            else:
                task.allocation = None
            
            # Handle multiple file uploads for editing
            files = request.FILES.getlist('attachments')
            for file in files:
                if file.size > 25 * 1024 * 1024:  # 25MB limit per file
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({'success': False, 'message': f'File {file.name} exceeds 25MB limit'})
                    messages.error(request, f'File {file.name} exceeds 25MB limit')
                    return redirect('accounts:task_management')
                
                # Create new attachment
                TaskAttachment.objects.create(
                    task=task,
                    file=file,
                    file_name=file.name,
                    file_size=file.size
                )
            
            task.save()
            
            # Send email to expert if newly allocated
            if task.allocation and old_allocation != task.allocation:
                send_expert_allocation_email(request, task, task.allocation)
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                success_message = 'Expert allocated successfully!' if is_quick_allocation else 'Task updated successfully'
                return JsonResponse({'success': True, 'message': success_message})
            messages.success(request, 'Task updated successfully')
            
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': str(e)})
            messages.error(request, f'Error updating task: {str(e)}')
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        experts = User.objects.filter(role='expert', is_active=True)
        
        # Get existing attachments
        attachments = task.task_attachments.all()
        attachment_data = []
        
        for attachment in attachments:
            attachment_data.append({
                'id': attachment.id,
                'file_name': attachment.file_name,
                'file_size': attachment.file_size,
                'file_size_mb': attachment.file_size_mb,
                'file_url': attachment.file.url,
                'uploaded_at': attachment.uploaded_at.strftime('%B %d, %Y at %I:%M %p')
            })
        
        data = {
            'id': task.id,
            'task_code': task.task_code,
            'module_code': task.module_code,
            'module_name': task.module_name,
            'word_count': task.word_count,
            'additional_words': task.additional_words,
            'deadline': task.deadline.strftime('%Y-%m-%dT%H:%M'),
            'quoted_price': str(task.quoted_price),
            'currency': task.currency,
            'allocation_id': task.allocation.id if task.allocation else None,
            'status': task.status,
            'notes': task.notes or '',
            'status_choices': Task.STATUS_CHOICES,
            'experts': [{'id': expert.id, 'username': expert.username, 'name': f"{expert.first_name} {expert.last_name}"} for expert in experts],
            'attachments': attachment_data,
        }
        return JsonResponse(data)
    
    return redirect('accounts:task_management')

@login_required
@require_POST
def task_delete(request, task_id):
    if request.user.role not in ['admin', 'manager']:
        return JsonResponse({'success': False, 'message': 'Unauthorized'})
    
    task = get_object_or_404(Task, id=task_id)
    
    try:
        task_code = task.task_code
        # Delete associated attachments
        for attachment in task.task_attachments.all():
            if attachment.file:
                attachment.file.delete(save=False)
            attachment.delete()
        
        # Delete old attachment field if exists
        if task.attachments:
            task.attachments.delete()
        
        task.delete()
        return JsonResponse({'success': True, 'message': f'Task {task_code} deleted successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})

@login_required
@require_POST
def delete_attachment(request, attachment_id):
    if request.user.role not in ['admin', 'manager']:
        return JsonResponse({'success': False, 'message': 'Unauthorized'})
    
    try:
        attachment = get_object_or_404(TaskAttachment, id=attachment_id)
        file_name = attachment.file_name
        
        # Delete the file from storage
        if attachment.file:
            attachment.file.delete(save=False)
        
        # Delete the database record
        attachment.delete()
        
        return JsonResponse({'success': True, 'message': f'Attachment "{file_name}" deleted successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Error deleting attachment: {str(e)}'})

def send_expert_allocation_email(request, task, expert):
    """Send email notification to expert when task is allocated"""
    if not expert.email:
        return False
    
    try:
        # Get task attachments
        attachments = task.task_attachments.all()
        attachments_html = ''
        
        if attachments:
            attachments_html = '''
            <div style="margin: 20px 0;">
                <h3 style="color: #333; margin-bottom: 15px;">📎 Task Attachments:</h3>
                <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 4px solid #667eea;">
            '''
            for attachment in attachments:
                # Build full download URL
                download_url = request.build_absolute_uri(attachment.file.url)
                attachments_html += f'''
                    <div style="margin: 12px 0; padding: 12px; background: white; border-radius: 8px; border: 1px solid #e0e0e0; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                        <div style="display: flex; align-items: center; justify-content: space-between;">
                            <div style="flex: 1;">
                                <div style="font-weight: bold; color: #333; margin-bottom: 4px;">
                                    <i class="fas fa-file" style="color: #667eea; margin-right: 8px;"></i>
                                    {attachment.file_name}
                                </div>
                                <div style="font-size: 0.85rem; color: #666;">
                                    Size: {attachment.file_size_mb} MB • Uploaded: {attachment.uploaded_at.strftime('%B %d, %Y at %I:%M %p')}
                                </div>
                            </div>
                            <div style="margin-left: 15px;">
                                <a href="{download_url}" style="background: #667eea; color: white; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-size: 0.9rem; font-weight: 600; display: inline-block;">
                                    <i class="fas fa-download" style="margin-right: 6px;"></i>Download
                                </a>
                            </div>
                        </div>
                    </div>
                '''
            attachments_html += '''
                </div>
                <div style="margin-top: 12px; padding: 10px; background: rgba(102, 126, 234, 0.1); border-radius: 6px; text-align: center;">
                    <small style="color: #667eea; font-weight: 600;">
                        <i class="fas fa-info-circle" style="margin-right: 4px;"></i>
                        Click the download buttons above to access all task files
                    </small>
                </div>
            </div>
            '''
        else:
            attachments_html = '''
            <div style="margin: 20px 0;">
                <h3 style="color: #333; margin-bottom: 15px;">📎 Task Attachments:</h3>
                <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 4px solid #ffc107; text-align: center;">
                    <p style="color: #856404; margin: 0; font-style: italic;">
                        <i class="fas fa-info-circle" style="margin-right: 6px;"></i>
                        No attachments provided for this task
                    </p>
                </div>
            </div>
            '''
        
        subject = f'New Task Allocated: {task.task_code} - {task.module_name}'
        
        html_message = f'''
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
        </head>
        <body style="margin: 0; padding: 0; font-family: Arial, sans-serif;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 20px;">
                <div style="max-width: 700px; margin: 0 auto;">
                    <div style="background: rgba(255, 255, 255, 0.95); border-radius: 20px; padding: 40px; box-shadow: 0 25px 45px rgba(0, 0, 0, 0.15);">
                        <div style="text-align: center; margin-bottom: 30px;">
                            <h1 style="font-size: 2.5rem; font-weight: bold; letter-spacing: 3px; color: #667eea; margin-bottom: 10px;">TEXVO</h1>
                            <p style="color: #666; font-size: 1.1rem; margin: 0;">New Task Allocation</p>
                        </div>
                        
                        <h2 style="color: #333; text-align: center; margin-bottom: 20px;">Hello {expert.first_name or expert.username}! 👋</h2>
                        
                        <p style="color: #666; font-size: 1.1rem; line-height: 1.6; text-align: center; margin-bottom: 30px;">
                            A new task has been allocated to you. Please review the details below and download any necessary files.
                        </p>
                        
                        <div style="background: #f8f9fa; border-radius: 15px; padding: 25px; margin: 20px 0; border-left: 5px solid #667eea;">
                            <h3 style="color: #333; margin-bottom: 20px;">📋 Task Details</h3>
                            <table style="width: 100%; border-collapse: collapse;">
                                <tr>
                                    <td style="padding: 8px 0; font-weight: bold; color: #333; width: 40%;">Task Code:</td>
                                    <td style="padding: 8px 0; color: #666;">{task.task_code}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 0; font-weight: bold; color: #333;">Client:</td>
                                    <td style="padding: 8px 0; color: #666;">{task.client.username} - {task.client.first_name} {task.client.last_name}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 0; font-weight: bold; color: #333;">Module:</td>
                                    <td style="padding: 8px 0; color: #666;">{task.module_code} - {task.module_name}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 0; font-weight: bold; color: #333;">Word Count:</td>
                                    <td style="padding: 8px 0; color: #666;">{task.word_count}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 0; font-weight: bold; color: #333;">Additional Words:</td>
                                    <td style="padding: 8px 0; color: #666;">{task.additional_words}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 0; font-weight: bold; color: #333;">Deadline:</td>
                                    <td style="padding: 8px 0; color: #dc3545; font-weight: bold;">{task.deadline.strftime('%B %d, %Y at %I:%M %p')}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 0; font-weight: bold; color: #333;">Status:</td>
                                    <td style="padding: 8px 0; color: #28a745; font-weight: bold;">In Progress</td>
                                </tr>
                            </table>
                        </div>
                        
                        {attachments_html}
                        
                        <div style="background: rgba(255, 193, 7, 0.1); border: 1px solid rgba(255, 193, 7, 0.3); border-radius: 10px; padding: 20px; margin: 25px 0; text-align: center;">
                            <h4 style="color: #856404; margin: 0 0 10px 0;">
                                <i class="fas fa-clock" style="margin-right: 8px;"></i>Important Deadline Notice
                            </h4>
                            <p style="color: #856404; margin: 0; font-size: 1rem;">
                                Please complete this task by <strong>{task.deadline.strftime('%B %d, %Y at %I:%M %p')}</strong>
                            </p>
                        </div>
                        
                        <div style="background: #e3f2fd; padding: 20px; border-radius: 10px; margin: 20px 0;">
                            <h4 style="color: #1976d2; margin-bottom: 12px;">
                                <i class="fas fa-sticky-note" style="margin-right: 8px;"></i>Additional Notes:
                            </h4>
                            <p style="color: #333; margin: 0; line-height: 1.5;">{task.notes or 'No additional notes provided for this task.'}</p>
                        </div>
                        
                        <div style="background: rgba(102, 126, 234, 0.1); border-radius: 10px; padding: 20px; margin: 25px 0; text-align: center;">
                            <h4 style="color: #667eea; margin: 0 0 10px 0;">
                                <i class="fas fa-laptop-code" style="margin-right: 8px;"></i>Next Steps
                            </h4>
                            <p style="color: #667eea; margin: 0; font-size: 0.95rem;">
                                1. Download and review all task attachments<br>
                                2. Log in to your dashboard for full task details<br>
                                3. Contact support if you have any questions
                            </p>
                        </div>
                        
                        <div style="margin-top: 40px; text-align: center; padding-top: 20px; border-top: 1px solid #eee;">
                            <p style="color: #999; font-size: 0.9rem; margin: 0;">
                                Best regards,<br>
                                <strong style="color: #667eea;">The Texvo Team</strong>
                            </p>
                            <p style="color: #ccc; font-size: 0.8rem; margin: 10px 0 0 0;">
                                This is an automated notification. Please do not reply to this email.
                            </p>
                        </div>
                    </div>
                </div>
            </div>
        </body>
        </html>
        '''
        
        # Enhanced plain text version with download links
        plain_message = f'''
New Task Allocated: {task.task_code}

Hello {expert.first_name or expert.username},

A new task has been allocated to you:

TASK DETAILS:
=============
Task Code: {task.task_code}
Client: {task.client.username} - {task.client.first_name} {task.client.last_name}
Module: {task.module_code} - {task.module_name}
Word Count: {task.word_count}
Additional Words: {task.additional_words}
Deadline: {task.deadline.strftime('%B %d, %Y at %I:%M %p')}
Status: In Progress

TASK ATTACHMENTS:
================'''
        
        if attachments:
            for attachment in attachments:
                download_url = request.build_absolute_uri(attachment.file.url)
                plain_message += f'''
• {attachment.file_name} ({attachment.file_size_mb} MB)
  Download: {download_url}
  Uploaded: {attachment.uploaded_at.strftime('%B %d, %Y at %I:%M %p')}
'''
        else:
            plain_message += '''
No attachments provided for this task.
'''

        plain_message += f'''

ADDITIONAL NOTES:
================
{task.notes or 'No additional notes provided for this task.'}

IMPORTANT: Please complete this task by {task.deadline.strftime('%B %d, %Y at %I:%M %p')}

Please log in to your dashboard for the complete task details and any additional resources.

Best regards,
The Texvo Team
        '''
        
        send_mail(
            subject,
            plain_message,
            settings.EMAIL_HOST_USER,
            [expert.email],
            fail_silently=False,            html_message=html_message,        )
        
        return True
        
    except Exception as e:
        print(f"Error sending expert allocation email: {str(e)}")
        return False

@login_required
def invoice_management(request):
    if request.user.role not in ['admin', 'manager']:
        return redirect('accounts:dashboard')
    
    # Get search query and filters
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    client_filter = request.GET.get('client', '')
    
    # Start with all invoices
    invoices = Invoice.objects.all().select_related('task', 'task__client')
    
    # Apply search filter
    if search_query:
        invoices = invoices.filter(
            Q(invoice_number__icontains=search_query) |
            Q(task__task_code__icontains=search_query) |
            Q(task__module_name__icontains=search_query) |
            Q(task__client__username__icontains=search_query) |
            Q(task__client__first_name__icontains=search_query) |
            Q(task__client__last_name__icontains=search_query)
        )
    
    # Apply status filter
    if status_filter:
        invoices = invoices.filter(payment_status=status_filter)
    
    # Apply client filter
    if client_filter:
        invoices = invoices.filter(task__client_id=client_filter)
    
    # Order by created date (newest first)
    invoices = invoices.order_by('-created_at')
    
    # Pagination
    paginator = Paginator(invoices, 10)  # Show 10 invoices per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get clients for dropdown
    clients = User.objects.filter(role='client', is_active=True)
    
    context = {
        'invoices': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
        'client_filter': client_filter,
        'status_choices': Invoice.PAYMENT_STATUS_CHOICES,
        'clients': clients,
        'total_invoices': invoices.count(),
    }
    
    return render(request, 'accounts/invoice_management.html', context)

@login_required
def create_invoice(request):
    if request.user.role not in ['admin', 'manager']:
        return redirect('accounts:dashboard')
    
    if request.method == 'POST':
        try:
            task_id = request.POST.get('task')
            amount_due = float(request.POST.get('amount_due', 0))
            
            # Validate task selection
            if not task_id:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'message': 'Task selection is required'})
                messages.error(request, 'Task selection is required')
                return redirect('accounts:invoice_management')
            
            try:
                task = Task.objects.get(id=task_id)
            except Task.DoesNotExist:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'message': 'Invalid task selected'})
                messages.error(request, 'Invalid task selected')
                return redirect('accounts:invoice_management')
            
            # Check if invoice already exists for this task
            if hasattr(task, 'invoice'):
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'message': 'Invoice already exists for this task'})
                messages.error(request, 'Invoice already exists for this task')
                return redirect('accounts:invoice_management')
              # Generate invoice number if not provided
            def generate_invoice_number():
                from datetime import datetime
                now = datetime.now()
                year_month = now.strftime('%Y%m')
                
                # Get the last invoice number for this month
                last_invoice = Invoice.objects.filter(
                    invoice_number__startswith=f'INV{year_month}'
                ).order_by('-invoice_number').first()
                
                if last_invoice:
                    try:
                        last_sequence = int(last_invoice.invoice_number[-4:])
                        new_sequence = last_sequence + 1
                    except (ValueError, IndexError):
                        new_sequence = 1
                else:
                    new_sequence = 1
                
                return f'INV{year_month}{new_sequence:04d}'
            
            invoice = Invoice.objects.create(
                task=task,
                amount_due=amount_due,
                currency=task.currency,
                invoice_number=generate_invoice_number()
            )
            
            # Send invoice email to client
            send_invoice_email_to_client(request, invoice)
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': f'Invoice {invoice.invoice_number} created and sent to client successfully'})
            messages.success(request, f'Invoice {invoice.invoice_number} created and sent to client successfully')
            
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': f'Error creating invoice: {str(e)}'})
            messages.error(request, f'Error creating invoice: {str(e)}')
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Get tasks without invoices
        tasks_without_invoices = Task.objects.filter(invoice__isnull=True).select_related('client')
        data = {
            'tasks': [{'id': task.id, 'task_code': task.task_code, 'module_name': task.module_name, 
                      'client_name': f"{task.client.first_name} {task.client.last_name}", 
                      'quoted_price': str(task.quoted_price),
                      'currency': task.currency,
                      'currency_symbol': task.currency_symbol,
                      'formatted_price': task.formatted_price} for task in tasks_without_invoices],
        }
        return JsonResponse(data)
    
    return redirect('accounts:invoice_management')

@login_required
def invoice_detail(request, invoice_id):
    if request.user.role not in ['admin', 'manager']:
        return redirect('accounts:dashboard')
    invoice = get_object_or_404(Invoice, id=invoice_id)
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Calculate balance due safely
        try:
            balance_due = invoice.amount_due - invoice.amount_paid
        except:
            balance_due = invoice.amount_due
        
        # Calculate payment percentage safely
        try:
            payment_percentage = (invoice.amount_paid / invoice.amount_due) * 100 if invoice.amount_due > 0 else 0
        except:
            payment_percentage = 0
        
        data = {
            'id': invoice.id,
            'invoice_number': invoice.invoice_number,
            'task_code': invoice.task.task_code,
            'module_name': invoice.task.module_name,
            'client_name': f"{invoice.task.client.first_name} {invoice.task.client.last_name}",
            'amount_due': str(invoice.amount_due),
            'formatted_amount_due': invoice.task.formatted_price,
            'amount_paid': str(invoice.amount_paid),
            'formatted_amount_paid': f"{invoice.task.currency_symbol}{invoice.amount_paid}",
            'balance_due': str(balance_due),
            'formatted_balance_due': f"{invoice.task.currency_symbol}{balance_due}",
            'payment_status': invoice.get_payment_status_display(),
            'payment_percentage': round(payment_percentage, 2),
            'payment_date': invoice.payment_date.strftime('%B %d, %Y at %I:%M %p') if invoice.payment_date else 'Not paid',
            'payment_receipt_url': getattr(invoice, 'payment_receipt', None) and invoice.payment_receipt.url if hasattr(invoice, 'payment_receipt') and invoice.payment_receipt else None,
            'payment_receipt_name': getattr(invoice, 'payment_receipt', None) and invoice.payment_receipt.name if hasattr(invoice, 'payment_receipt') and invoice.payment_receipt else None,
            'created_at': invoice.created_at.strftime('%B %d, %Y at %I:%M %p'),
            'updated_at': invoice.updated_at.strftime('%B %d, %Y at %I:%M %p'),
            'task_deadline': invoice.task.deadline.strftime('%B %d, %Y at %I:%M %p'),
        }
        return JsonResponse(data)
    
    return render(request, 'accounts/invoice_detail.html', {'invoice': invoice})

@login_required
def update_payment(request, invoice_id):
    if request.user.role not in ['admin', 'manager']:
        return redirect('accounts:dashboard')
    
    invoice = get_object_or_404(Invoice, id=invoice_id)    
    if request.method == 'POST':
        try:
            amount_paid = float(request.POST.get('amount_paid', 0))
            payment_status = request.POST.get('payment_status', invoice.payment_status)
            
            if amount_paid > invoice.amount_due:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'message': 'Amount paid cannot exceed amount due'})
                messages.error(request, 'Amount paid cannot exceed amount due')
                return redirect('accounts:invoice_management')
            
            # Handle payment receipt upload
            payment_receipt = request.FILES.get('payment_receipt')
            if payment_receipt:
                # Check file size (5MB limit)
                if payment_receipt.size > 5 * 1024 * 1024:
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({'success': False, 'message': 'Payment receipt file exceeds 5MB limit'})
                    messages.error(request, 'Payment receipt file exceeds 5MB limit')
                    return redirect('accounts:invoice_management')
                
                # Check file type (images and PDFs only)
                allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'application/pdf']
                if payment_receipt.content_type not in allowed_types:
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({'success': False, 'message': 'Only images (JPG, PNG, GIF) and PDF files are allowed for payment receipts'})
                    messages.error(request, 'Only images (JPG, PNG, GIF) and PDF files are allowed for payment receipts')
                    return redirect('accounts:invoice_management')
                
                # Delete old receipt if exists
                if hasattr(invoice, 'payment_receipt') and invoice.payment_receipt:
                    invoice.payment_receipt.delete(save=False)
                
                invoice.payment_receipt = payment_receipt
            
            invoice.amount_paid = amount_paid
            invoice.payment_status = payment_status
            
            # Set payment date if fully paid
            if amount_paid >= invoice.amount_due and not invoice.payment_date:
                invoice.payment_date = timezone.now()
            
            invoice.save()
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': 'Payment updated successfully'})
            messages.success(request, 'Payment updated successfully')
            
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': str(e)})
            messages.error(request, f'Error updating payment: {str(e)}')
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        data = {
            'id': invoice.id,
            'invoice_number': invoice.invoice_number,
            'amount_due': str(invoice.amount_due),
            'amount_paid': str(invoice.amount_paid),
            'payment_status': invoice.payment_status,
            'payment_receipt_url': getattr(invoice, 'payment_receipt', None) and invoice.payment_receipt.url if hasattr(invoice, 'payment_receipt') and invoice.payment_receipt else None,
            'payment_receipt_name': getattr(invoice, 'payment_receipt', None) and invoice.payment_receipt.name if hasattr(invoice, 'payment_receipt') and invoice.payment_receipt else None,
            'status_choices': Invoice.PAYMENT_STATUS_CHOICES,
        }
        return JsonResponse(data)
    
    return redirect('accounts:invoice_management')

@login_required
@require_POST
def delete_invoice(request, invoice_id):
    if request.user.role not in ['admin', 'manager']:
        return JsonResponse({'success': False, 'message': 'Unauthorized'})
    
    invoice = get_object_or_404(Invoice, id=invoice_id)
    
    try:
        invoice_number = invoice.invoice_number
        invoice.delete()
        return JsonResponse({'success': True, 'message': f'Invoice {invoice_number} deleted successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})

@login_required
@require_POST
def resend_invoice(request, invoice_id):
    if request.user.role not in ['admin', 'manager']:
        return JsonResponse({'success': False, 'message': 'Unauthorized'})
    
    invoice = get_object_or_404(Invoice, id=invoice_id)
    
    try:
        # Send invoice email to client
        success = send_invoice_email_to_client(request, invoice)
        if success:
            return JsonResponse({'success': True, 'message': f'Invoice {invoice.invoice_number} resent to client successfully'})
        else:
            return JsonResponse({'success': False, 'message': 'Failed to send invoice email - client may not have an email address'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Error resending invoice: {str(e)}'})

@login_required
def calendar_view(request):
    if request.user.role not in ['admin', 'manager']:
        return redirect('accounts:dashboard')
    
    # Get current date parameters
    year = int(request.GET.get('year', timezone.now().year))
    month = int(request.GET.get('month', timezone.now().month))
    
    # Create date range for the month
    start_date = timezone.datetime(year, month, 1)
    if month == 12:
        end_date = timezone.datetime(year + 1, 1, 1) - timezone.timedelta(days=1)
    else:
        end_date = timezone.datetime(year, month + 1, 1) - timezone.timedelta(days=1)
    
    # Get all tasks for the month
    tasks = Task.objects.filter(
        deadline__date__range=[start_date.date(), end_date.date()]
    ).select_related('client', 'allocation').order_by('deadline')
    
    # Get all invoices with payment dates in the month
    invoices = Invoice.objects.filter(
        payment_date__date__range=[start_date.date(), end_date.date()]
    ).select_related('task', 'task__client')
    
    # Organize events by date
    calendar_events = {}
    
    # Add task deadlines
    for task in tasks:
        date_key = task.deadline.date().isoformat()
        if date_key not in calendar_events:
            calendar_events[date_key] = {'tasks': [], 'payments': []}
          # Determine task status and payment info
        payment_info = None
        if hasattr(task, 'invoice'):
            payment_info = {
                'amount_due': task.invoice.amount_due,
                'amount_paid': task.invoice.amount_paid,
                'balance_due': task.invoice.balance_due,
                'payment_status': task.invoice.payment_status,
                'payment_percentage': task.invoice.payment_percentage,
                'formatted_amount': task.formatted_price
            }
        
        calendar_events[date_key]['tasks'].append({
            'id': task.id,
            'task_code': task.task_code,
            'module_name': task.module_name,
            'client_name': f"{task.client.first_name} {task.client.last_name}",
            'status': task.status,
            'deadline': task.deadline.isoformat(),
            'allocation': task.allocation.username if task.allocation else 'Unassigned',
            'payment_info': payment_info
        })
    
    # Add payment dates
    for invoice in invoices:
        date_key = invoice.payment_date.date().isoformat()
        if date_key not in calendar_events:
            calendar_events[date_key] = {'tasks': [], 'payments': []}
            calendar_events[date_key]['payments'].append({
            'invoice_number': invoice.invoice_number,
            'task_code': invoice.task.task_code,
            'client_name': f"{invoice.task.client.first_name} {invoice.task.client.last_name}",
            'amount_paid': str(invoice.amount_paid),
            'payment_status': invoice.payment_status,
            'formatted_amount': f"{invoice.task.currency_symbol}{invoice.amount_paid}"
        })
    
    # Get summary statistics
    total_tasks = tasks.count()
    completed_tasks = tasks.filter(status='Completed').count()
    pending_tasks = tasks.filter(status='Pending').count()
    in_progress_tasks = tasks.filter(status='InProgress').count()
    
    total_invoices = Invoice.objects.filter(
        task__deadline__date__range=[start_date.date(), end_date.date()]
    ).count()
    paid_invoices = Invoice.objects.filter(
        task__deadline__date__range=[start_date.date(), end_date.date()],
        payment_status='Completed'
    ).count()    
    context = {
        'calendar_events': json.dumps(calendar_events),
        'current_year': year,
        'current_month': month,
        'current_date': timezone.now().date(),
        'month_name': start_date.strftime('%B'),
        'total_tasks': total_tasks,
        'completed_tasks': completed_tasks,
        'pending_tasks': pending_tasks,
        'in_progress_tasks': in_progress_tasks,
        'total_invoices': total_invoices,
        'paid_invoices': paid_invoices,
        'prev_month': (month - 1) if month > 1 else 12,
        'prev_year': year if month > 1 else year - 1,
        'next_month': (month + 1) if month < 12 else 1,
        'next_year': year if month < 12 else year + 1,
    }
    
    return render(request, 'accounts/calendar_view.html', context)

@login_required
def calendar_view_new(request):
    if request.user.role not in ['admin', 'manager']:
        return redirect('accounts:dashboard')
    
    # Get current date parameters
    year = int(request.GET.get('year', timezone.now().year))
    month = int(request.GET.get('month', timezone.now().month))
    
    # Create date range for the month
    start_date = timezone.datetime(year, month, 1)
    if month == 12:
        end_date = timezone.datetime(year + 1, 1, 1) - timezone.timedelta(days=1)
    else:
        end_date = timezone.datetime(year, month + 1, 1) - timezone.timedelta(days=1)
    
    # Get all tasks for the month
    tasks = Task.objects.filter(
        deadline__date__range=[start_date.date(), end_date.date()]
    ).select_related('client', 'allocation').order_by('deadline')
    
    # Get all invoices with payment dates in the month
    invoices = Invoice.objects.filter(
        payment_date__date__range=[start_date.date(), end_date.date()]
    ).select_related('task', 'task__client')
    
    # Organize events by date
    calendar_events = {}
    
    # Add task deadlines
    for task in tasks:
        date_key = task.deadline.date().isoformat()
        if date_key not in calendar_events:
            calendar_events[date_key] = {'tasks': [], 'payments': []}
        
        # Determine task status and payment info
        payment_info = None
        try:
            invoice = getattr(task, 'invoice', None)
            if invoice:
                payment_info = {
                    'amount_due': str(invoice.amount_due),
                    'amount_paid': str(invoice.amount_paid),
                    'balance_due': str(invoice.balance_due),
                    'payment_status': invoice.payment_status,
                    'payment_percentage': round(invoice.payment_percentage, 2),
                    'formatted_amount': task.formatted_price
                }
        except Exception:
            payment_info = None
        
        calendar_events[date_key]['tasks'].append({
            'id': task.id,
            'task_code': task.task_code,
            'module_name': task.module_name,
            'client_name': f"{task.client.first_name} {task.client.last_name}",
            'status': task.status,
            'deadline': task.deadline.strftime('%Y-%m-%d %H:%M:%S'),
            'allocation': task.allocation.username if task.allocation else 'Unassigned',
            'payment_info': payment_info
        })
    
    # Add payment dates
    for invoice in invoices:
        date_key = invoice.payment_date.date().isoformat()
        if date_key not in calendar_events:
            calendar_events[date_key] = {'tasks': [], 'payments': []}
        
        calendar_events[date_key]['payments'].append({
            'invoice_number': invoice.invoice_number,
            'task_code': invoice.task.task_code,
            'client_name': f"{invoice.task.client.first_name} {invoice.task.client.last_name}",
            'amount_paid': str(invoice.amount_paid),
            'payment_status': invoice.payment_status,
            'formatted_amount': f"{invoice.task.currency_symbol}{invoice.amount_paid}"
        })
    
    # Get summary statistics
    total_tasks = tasks.count()
    completed_tasks = tasks.filter(status='Completed').count()
    pending_tasks = tasks.filter(status='Pending').count()
    in_progress_tasks = tasks.filter(status='InProgress').count()
    
    total_invoices = Invoice.objects.filter(
        task__deadline__date__range=[start_date.date(), end_date.date()]
    ).count()
    paid_invoices = Invoice.objects.filter(
        task__deadline__date__range=[start_date.date(), end_date.date()],
        payment_status='Completed'
    ).count()    
    context = {
        'calendar_events': json.dumps(calendar_events),
        'current_year': year,
        'current_month': month,
        'current_date': timezone.now().date().isoformat(),
        'month_name': start_date.strftime('%B'),
        'total_tasks': total_tasks,
        'completed_tasks': completed_tasks,
        'pending_tasks': pending_tasks,
        'in_progress_tasks': in_progress_tasks,
        'total_invoices': total_invoices,
        'paid_invoices': paid_invoices,
        'prev_month': (month - 1) if month > 1 else 12,
        'prev_year': year if month > 1 else year - 1,
        'next_month': (month + 1) if month < 12 else 1,
        'next_year': year if month < 12 else year + 1,
    }
    
    return render(request, 'accounts/calendar_view.html', context)

# Simple Calendar View with Proper JSON Serialization
@login_required  
def calendar_simple(request):
    if request.user.role not in ['admin', 'manager']:
        return redirect('accounts:dashboard')
    

    
    # Default to current month/year
    year = int(request.GET.get('year', timezone.now().year))
    month = int(request.GET.get('month', timezone.now().month))
    
    # Get tasks for the month
    start_date = timezone.datetime(year, month, 1).date()
    if month == 12:
        end_date = timezone.datetime(year + 1, 1, 1).date() - timezone.timedelta(days=1)
    else:
        end_date = timezone.datetime(year, month + 1, 1).date() - timezone.timedelta(days=1)
    
    tasks = Task.objects.filter(deadline__date__range=[start_date, end_date])
    invoices = Invoice.objects.filter(payment_date__date__range=[start_date, end_date])
    
    # Simple event structure
    events = {}
    
    # Add tasks
    for task in tasks:
        date_str = task.deadline.date().strftime('%Y-%m-%d')
        if date_str not in events:
            events[date_str] = {'tasks': [], 'payments': []}
        
        events[date_str]['tasks'].append({
            'task_code': task.task_code,
            'module_name': task.module_name,
            'client': f"{task.client.first_name} {task.client.last_name}",
            'status': task.status,
            'time': task.deadline.strftime('%H:%M')
        })
    
    # Add payments  
    for invoice in invoices:
        date_str = invoice.payment_date.date().strftime('%Y-%m-%d')
        if date_str not in events:
            events[date_str] = {'tasks': [], 'payments': []}
            
        events[date_str]['payments'].append({
            'invoice': invoice.invoice_number,
            'amount': str(invoice.amount_paid),
            'client': f"{invoice.task.client.first_name} {invoice.task.client.last_name}"
        })
    
    context = {
        'calendar_events': json.dumps(events),
        'current_year': year,
        'current_month': month,
        'current_date': timezone.now().date().strftime('%Y-%m-%d'),
        'month_name': timezone.datetime(year, month, 1).strftime('%B'),
        'total_tasks': tasks.count(),
        'completed_tasks': tasks.filter(status='Completed').count(),
        'pending_tasks': tasks.filter(status='Pending').count(),
        'in_progress_tasks': tasks.filter(status='InProgress').count(),
        'total_invoices': invoices.count(),
        'paid_invoices': invoices.filter(payment_status='Completed').count(),
        'prev_month': (month - 1) if month > 1 else 12,
        'prev_year': year if month > 1 else year - 1,
        'next_month': (month + 1) if month < 12 else 1,
        'next_year': year if month < 12 else year + 1,
    }
    
    return render(request, 'accounts/calendar_view.html', context)

def send_invoice_email_to_client(request, invoice):
    """Send invoice email to client with payment button based on currency"""
    client = invoice.task.client
    
    if not client.email:
        return False
    
    try:        # Create payment links and styled buttons for each currency (email-safe alternative)
        payment_links = {
            'EUR': 'https://razorpay.com/payment-button/pl_QfQP507YqaIa8B/view/?utm_source=payment_button&utm_medium=button&utm_campaign=payment_button',
            'USD': 'https://razorpay.com/payment-button/pl_QfQUphGIPKrC69/view/?utm_source=payment_button&utm_medium=button&utm_campaign=payment_button',
            'GBP': 'https://razorpay.com/payment-button/pl_QfQW8osUgorIa2/view/?utm_source=payment_button&utm_medium=button&utm_campaign=payment_button',
            'INR': 'https://razorpay.com/payment-button/pl_QfQaXl7R7AgOcG/view/?utm_source=payment_button&utm_medium=button&utm_campaign=payment_button',
        }
        
        payment_link = payment_links.get(invoice.task.currency, payment_links['INR'])
          # Create email-safe payment button HTML
        payment_button_html = f'''
            <div style="text-align: center; margin: 30px 0;">
                <table cellpadding="0" cellspacing="0" border="0" style="margin: 0 auto;">
                    <tr>
                        <td style="background: linear-gradient(135deg, #28a745 0%, #20c997 100%); padding: 0; border-radius: 12px; box-shadow: 0 8px 20px rgba(40, 167, 69, 0.3);">
                            <a href="{payment_link}" 
                               style="display: block; 
                                      padding: 18px 40px; 
                                      color: white; 
                                      text-decoration: none; 
                                      font-weight: bold; 
                                      font-size: 18px; 
                                      border-radius: 12px;
                                      font-family: Arial, sans-serif;"
                               target="_blank">
                                💳 Pay {invoice.task.currency_symbol}{invoice.amount_due - invoice.amount_paid} Now
                            </a>
                        </td>
                    </tr>
                </table>
            </div>
            <div style="text-align: center; margin: 15px 0;">
                <p style="color: #666; font-size: 14px; margin: 0; font-family: Arial, sans-serif;">
                    🔒 Secure payment powered by Razorpay
                </p>
            </div>
            <div style="text-align: center; margin: 20px 0; padding: 15px; background: rgba(40, 167, 69, 0.1); border-radius: 8px;">
                <p style="color: #28a745; margin: 0; font-weight: 600;">
                    ✅ Click the green button above to pay securely online
                </p>
            </div>
        '''
        
        subject = f'Invoice {invoice.invoice_number} - Payment Required'
        
        html_message = f'''
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    margin: 0;
                    padding: 0;
                    font-family: 'Arial', sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                }}
                .email-container {{
                    max-width: 700px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .email-card {{
                    background: rgba(255, 255, 255, 0.95);
                    backdrop-filter: blur(20px);
                    border-radius: 20px;
                    padding: 40px;
                    box-shadow: 0 25px 45px rgba(0, 0, 0, 0.15);
                }}
                .header {{
                    text-align: center;
                    margin-bottom: 30px;
                }}
                .logo {{
                    font-size: 2.5rem;
                    font-weight: bold;
                    letter-spacing: 3px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    background-clip: text;
                    margin-bottom: 10px;
                }}
                .subtitle {{
                    color: #666;
                    font-size: 1.1rem;
                }}
                .invoice-header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 25px;
                    border-radius: 15px;
                    margin: 25px 0;
                    text-align: center;
                }}
                .invoice-number {{
                    font-size: 2rem;
                    font-weight: bold;
                    margin-bottom: 10px;
                }}
                .invoice-amount {{
                    font-size: 1.5rem;
                    margin-bottom: 5px;
                }}
                .content {{
                    color: #333;
                    line-height: 1.6;
                    margin-bottom: 30px;
                }}
                .greeting {{
                    font-size: 1.2rem;
                    font-weight: 600;
                    color: #333;
                    margin-bottom: 20px;
                }}
                .message {{
                    font-size: 1rem;
                    margin-bottom: 25px;
                }}
                .invoice-details {{
                    background: #f8f9fa;
                    border-radius: 15px;
                    padding: 25px;
                    margin: 20px 0;
                    border-left: 5px solid #667eea;
                }}
                .invoice-table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin: 20px 0;
                }}
                .invoice-table th,
                .invoice-table td {{
                    padding: 12px 15px;
                    text-align: left;
                    border-bottom: 1px solid #e0e0e0;
                }}
                .invoice-table th {{
                    background: #667eea;
                    color: white;
                    font-weight: 600;
                }}
                .invoice-table tr:nth-child(even) {{
                    background: #f8f9fa;
                }}
                .payment-section {{
                    background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
                    color: white;
                    padding: 30px;
                    border-radius: 15px;
                    margin: 30px 0;
                    text-align: center;
                }}
                .payment-title {{
                    font-size: 1.5rem;
                    font-weight: bold;
                    margin-bottom: 15px;
                }}
                .payment-button-container {{
                    margin: 25px 0;
                    padding: 20px;
                    background: rgba(255, 255, 255, 0.1);
                    border-radius: 10px;
                }}
                .security-note {{
                    background: rgba(255, 193, 7, 0.1);
                    border: 1px solid rgba(255, 193, 7, 0.3);
                    border-radius: 10px;
                    padding: 20px;
                    margin: 25px 0;
                }}
                .security-note h4 {{
                    color: #856404;
                    margin: 0 0 10px 0;
                }}
                .security-note p {{
                    margin: 0;
                    color: #856404;
                    font-size: 0.9rem;
                }}
                .footer {{
                    margin-top: 40px;
                    padding-top: 20px;
                    border-top: 1px solid #eee;
                    text-align: center;
                    color: #999;
                    font-size: 0.9rem;
                }}
                .contact-info {{
                    background: rgba(102, 126, 234, 0.1);
                    border-radius: 10px;
                    padding: 20px;
                    margin: 25px 0;
                    text-align: center;
                }}
                @media (max-width: 600px) {{
                    .email-card {{
                        padding: 20px;
                        margin: 10px;
                    }}
                    .logo {{
                        font-size: 2rem;
                    }}
                    .invoice-number {{
                        font-size: 1.5rem;
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="email-container">
                <div class="email-card">
                    <div class="header">
                        <div class="logo">TEXVO</div>
                        <div class="subtitle">Invoice & Payment Request</div>
                    </div>                        <div class="invoice-header">
                        <div class="invoice-number">Invoice #{invoice.invoice_number}</div>
                        <div class="invoice-amount">Amount Due: {invoice.task.formatted_price}</div>
                        <div class="invoice-amount">Balance Due: {invoice.task.currency_symbol}{invoice.amount_due - invoice.amount_paid}</div>
                        <div style="font-size: 0.9rem; opacity: 0.9;">Task: {invoice.task.task_code} - {invoice.task.module_name}</div>
                    </div>
                    
                    <div class="content">
                        <div class="greeting">Dear {client.first_name or client.username},</div>
                        
                        <div class="message">
                            We hope this email finds you well. Please find below the invoice for your recent project with TEXVO. 
                            We appreciate your business and look forward to your prompt payment.
                        </div>
                        
                        <div class="invoice-details">
                            <h3 style="color: #333; margin-bottom: 20px;">📋 Invoice Details</h3>
                            <table class="invoice-table">
                                <tr>
                                    <th>Description</th>
                                    <th>Details</th>
                                </tr>
                                <tr>
                                    <td><strong>Invoice Number</strong></td>
                                    <td>{invoice.invoice_number}</td>
                                </tr>
                                <tr>
                                    <td><strong>Task Code</strong></td>
                                    <td>{invoice.task.task_code}</td>
                                </tr>
                                <tr>
                                    <td><strong>Project/Module</strong></td>
                                    <td>{invoice.task.module_name}</td>
                                </tr>
                                <tr>
                                    <td><strong>Word Count</strong></td>
                                    <td>{invoice.task.word_count} words</td>
                                </tr>
                                <tr>
                                    <td><strong>Additional Words</strong></td>
                                    <td>{invoice.task.additional_words} words</td>
                                </tr>
                                <tr>
                                    <td><strong>Project Deadline</strong></td>
                                    <td>{invoice.task.deadline.strftime('%B %d, %Y at %I:%M %p')}</td>
                                </tr>                                <tr style="background: #e8f5e8; font-weight: bold;">
                                    <td><strong>Balance Due</strong></td>
                                    <td><strong>{invoice.task.currency_symbol}{invoice.amount_due - invoice.amount_paid}</strong></td>
                                </tr>
                            </table>
                        </div>
                        
                        <div class="payment-section">
                            <div class="payment-title">💳 Secure Online Payment</div>
                            <p style="margin: 15px 0; font-size: 1.1rem;">
                                Click the button below to make a secure payment through our trusted payment gateway
                            </p>
                            <div class="payment-button-container">
                                {payment_button_html}
                            </div>
                            <p style="margin: 10px 0; font-size: 0.9rem; opacity: 0.9;">
                                🔒 Powered by Razorpay - Safe, Secure & Encrypted
                            </p>
                        </div>
                        
                        <div class="security-note">
                            <h4>🛡️ Payment Security Information</h4>
                            <p>
                                • All payments are processed through Razorpay's secure payment gateway<br>
                                • Your card details are encrypted and never stored on our servers<br>
                                • You will receive a payment confirmation email upon successful transaction<br>
                                • Multiple payment methods accepted: Cards, UPI, Net Banking, Wallets
                            </p>
                        </div>
                        
                        <div class="contact-info">
                            <h4 style="color: #667eea; margin: 0 0 15px 0;">
                                💬 Need Help or Have Questions?
                            </h4>
                            <p style="color: #667eea; margin: 0; font-size: 0.95rem;">
                                Our support team is here to assist you.<br>
                                Contact us for any payment-related queries or technical support.
                            </p>
                        </div>
                    </div>
                    
                    <div class="footer">
                        <p><strong style="color: #667eea;">Thank you for choosing TEXVO!</strong></p>
                        <p style="margin: 15px 0 0 0;">
                            This is an automated invoice. Please do not reply directly to this email.
                        </p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        '''
          # Plain text version
        plain_message = f'''
TEXVO - Invoice #{invoice.invoice_number}

Dear {client.first_name or client.username},

Please find below the invoice for your recent project with TEXVO.

INVOICE DETAILS:
===============
Invoice Number: {invoice.invoice_number}
Task Code: {invoice.task.task_code}
Project/Module: {invoice.task.module_name}
Word Count: {invoice.task.word_count} words
Additional Words: {invoice.task.additional_words} words
Project Deadline: {invoice.task.deadline.strftime('%B %d, %Y at %I:%M %p')}

PAYMENT SUMMARY:
===============
Total Amount Due: {invoice.task.formatted_price}
Amount Paid: {invoice.task.currency_symbol}{invoice.amount_paid}
Balance Due: {invoice.task.currency_symbol}{invoice.amount_due - invoice.amount_paid}

PAYMENT INFORMATION:
===================
To make a payment, please visit: {payment_link}
Currency: {invoice.task.get_currency_display()}
Payment Status: {invoice.get_payment_status_display()}

Thank you for choosing TEXVO!

Best regards,
The TEXVO Team
        '''
        
        send_mail(
            subject,
            plain_message,
            settings.EMAIL_HOST_USER,
            [client.email],
            fail_silently=False,
            html_message=html_message,
        )
        return True
        
    except Exception as e:
        print(f"Error sending invoice email: {str(e)}")
        return False

@login_required
def get_available_tasks(request):
    """API endpoint to get tasks available for invoice creation"""
    if request.user.role not in ['admin', 'manager']:
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    # Get completed tasks without invoices
    available_tasks = Task.objects.filter(
        status='Completed'
    ).exclude(
        id__in=Invoice.objects.values_list('task_id', flat=True)
    ).select_related('client')
    
    tasks_data = []
    for task in available_tasks:
        tasks_data.append({
            'id': task.id,
            'task_code': task.task_code,
            'module_name': task.module_name,
            'client_name': f"{task.client.first_name} {task.client.last_name}",
            'quoted_price': str(task.quoted_price),
            'currency': task.currency,
            'currency_symbol': task.currency_symbol,
        })
    
    return JsonResponse({'tasks': tasks_data})

@login_required
def settings_view(request):
    context = {'user': request.user}
    user = request.user

    # Change password with old password
    if request.method == 'POST' and 'old_password' in request.POST:
        old_password = request.POST.get('old_password')
        new1 = request.POST.get('new_password1')
        new2 = request.POST.get('new_password2')
        if not user.check_password(old_password):
            context['password_change_error'] = "Old password is incorrect."
        elif new1 != new2:
            context['password_change_error'] = "New passwords do not match."
        elif len(new1) < 6:
            context['password_change_error'] = "Password must be at least 6 characters."
        else:
            user.set_password(new1)
            user.save()
            update_session_auth_hash(request, user)
            context['password_change_success'] = "Password changed successfully."

    # Request OTP for password reset
    elif request.method == 'POST' and request.POST.get('otp_request') == '1':
        otp = str(random.randint(100000, 999999))
        request.session['settings_otp'] = otp
        request.session['settings_otp_user'] = user.pk
        # Send OTP to email
        send_mail(
            'Your TEXVO OTP for Password Reset',
            f'Your OTP for password reset is: {otp}',
            settings.EMAIL_HOST_USER,
            [user.email],
            fail_silently=False,
        )
        context['otp_sent'] = True

    # Verify OTP and reset password
    elif request.method == 'POST' and request.POST.get('otp_verify') == '1':
        otp = request.POST.get('otp')
        new1 = request.POST.get('reset_password1')
        new2 = request.POST.get('reset_password2')
        session_otp = request.session.get('settings_otp')
        session_user = request.session.get('settings_otp_user')
        if not session_otp or not session_user or int(session_user) != user.pk:
            context['otp_error'] = "OTP session expired. Please request again."
        elif otp != session_otp:
            context['otp_error'] = "Invalid OTP."
        elif new1 != new2:
            context['otp_error'] = "Passwords do not match."
        elif len(new1) < 6:
            context['otp_error'] = "Password must be at least 6 characters."
        else:
            user.set_password(new1)
            user.save()
            update_session_auth_hash(request, user)
            context['otp_success'] = "Password reset successfully."
            # Clear OTP session
            request.session.pop('settings_otp', None)
            request.session.pop('settings_otp_user', None)

    return render(request, 'accounts/settings.html', context)

@login_required
def expert_payments(request):
    if request.user.role != 'admin':
        return redirect('accounts:dashboard')
    
    # Year filter (default to current year)
    year = int(request.GET.get('year', timezone.now().year))
    
    # Get all experts
    experts = User.objects.filter(role='expert', is_active=True)
    
    # Dictionary to store expert data
    expert_data = {}
    
    # Get all completed tasks with allocation
    tasks = Task.objects.filter(
        status='Completed',
        allocation__isnull=False,
        allocation__role='expert',
        deadline__year=year
    ).annotate(
        month=ExtractMonth('deadline')
    ).values(
        'allocation', 'month'
    ).annotate(
        total_words=Sum(F('word_count') + F('additional_words')),
        task_count=Count('id')
    ).order_by('allocation', 'month')
    
    # Initialize expert pay rates
    for expert in experts:
        # Get or create pay rate for this expert
        pay_rate, created = ExpertPayRate.objects.get_or_create(
            expert=expert,
            defaults={'price_per_word': 0.500, 'currency': 'INR'}
        )
        
        # Initialize expert data structure
        expert_data[expert.id] = {
            'id': expert.id,
            'username': expert.username,
            'name': f"{expert.first_name} {expert.last_name}".strip() or expert.username,
            'pay_rate': pay_rate,
            'monthly_data': {},
            'yearly_total': {
                'words': 0,
                'tasks': 0,
                'payment': 0
            }
        }
        
        # Initialize monthly data (1-12)
        for month in range(1, 13):
            expert_data[expert.id]['monthly_data'][month] = {
                'words': 0, 
                'tasks': 0,
                'payment': 0,
                'month_name': calendar.month_name[month]
            }
    
    # Calculate monthly data for each expert
    for task in tasks:
        expert_id = task['allocation']
        month = task['month']
        words = task['total_words']
        task_count = task['task_count']
        
        if expert_id in expert_data:
            # Add words to monthly data
            expert_data[expert_id]['monthly_data'][month]['words'] += words
            expert_data[expert_id]['monthly_data'][month]['tasks'] += task_count
            
            # Calculate payment based on pay rate
            pay_rate = expert_data[expert_id]['pay_rate'].price_per_word
            payment = words * pay_rate
            
            expert_data[expert_id]['monthly_data'][month]['payment'] += payment
            
            # Update yearly totals
            expert_data[expert_id]['yearly_total']['words'] += words
            expert_data[expert_id]['yearly_total']['tasks'] += task_count
            expert_data[expert_id]['yearly_total']['payment'] += payment
    
    # Handle PPW updates via AJAX
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        try:
            expert_id = request.POST.get('expert_id')
            new_ppw = request.POST.get('ppw')
            currency = request.POST.get('currency', 'INR')
            
            # Validate the data
            if not expert_id or not new_ppw:
                return JsonResponse({'success': False, 'message': 'Missing required fields'})
            
            try:
                expert = User.objects.get(id=expert_id, role='expert')
                pay_rate, created = ExpertPayRate.objects.get_or_create(expert=expert)
                
                pay_rate.price_per_word = new_ppw
                pay_rate.currency = currency
                pay_rate.save()
                
                return JsonResponse({
                    'success': True, 
                    'message': f'Updated {expert.username} rate to {currency} {new_ppw}/word'
                })
            except Exception as e:
                return JsonResponse({'success': False, 'message': str(e)})
                
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})
    
    # Available years for filter (last 5 years)
    current_year = timezone.now().year
    available_years = list(range(current_year - 4, current_year + 1))
    
    context = {
        'experts': experts,
        'expert_data': expert_data,
        'current_year': year,
        'available_years': available_years,
        'months': [{'number': m, 'name': calendar.month_name[m]} for m in range(1, 13)],
        'currency_choices': Invoice.CURRENCY_CHOICES,
    }
    
    return render(request, 'accounts/expert_payments.html', context)

