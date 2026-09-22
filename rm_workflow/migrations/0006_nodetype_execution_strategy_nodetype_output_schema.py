import drf_base_app.models.fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("rm_workflow", "0005_compiledversion"),
    ]

    operations = [
        migrations.AddField(
            model_name="nodetype",
            name="execution_strategy",
            field=drf_base_app.models.fields.CharField(
                choices=[("worker", "worker"), ("intercept", "intercept")],
                default="worker",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="nodetype",
            name="output_schema",
            field=drf_base_app.models.fields.JSONField(blank=True, null=True),
        ),
    ]
