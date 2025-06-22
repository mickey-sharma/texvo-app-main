# Generated migration for adding payment_receipt field to Invoice model

from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='payment_receipt',
            field=models.FileField(blank=True, null=True, upload_to='invoices/receipts/'),
        ),
    ]