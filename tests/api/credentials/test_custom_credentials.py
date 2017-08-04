import towerkit.exceptions as exc
from towerkit.utils import to_str
import pytest

from tests.api import Base_Api_Test


@pytest.mark.api
@pytest.mark.skip_selenium
@pytest.mark.usefixtures('authtoken', 'install_enterprise_license_unlimited')
class TestCustomCredentials(Base_Api_Test):

    @pytest.mark.parametrize('field_type', ['string', 'boolean'])
    def test_unprovided_required_input_field(self, factories, field_type):
        inputs = dict(fields=[dict(id='field', label='Field', type=field_type)], required=['field'])
        credential_type = factories.credential_type(inputs=inputs)

        with pytest.raises(exc.BadRequest) as e:
            factories.v2_credential(credential_type=credential_type, inputs={})
        assert e.value.message == {'inputs': {'field': ["required for {0.name}".format(credential_type)]}}

    def test_ssh_private_key_input_field_validated(self, factories):
        credential_type = factories.credential_type(inputs=dict(fields=[dict(id='field_name',
                                                                             label='FieldName',
                                                                             format='ssh_private_key')]))

        with pytest.raises(exc.BadRequest) as e:
            factories.v2_credential(credential_type=credential_type, inputs=dict(field_name='NotAnRSAKey'))
        assert e.value.message == {'inputs': {'field_name': ['Invalid certificate or key: NotAnRSAKey...']}}

    def test_extraneous_input_field(self, factories):
        inputs = dict(fields=[dict(id='field', label='Field')])
        credential_type = factories.credential_type(inputs=inputs)

        with pytest.raises(exc.BadRequest) as e:
            factories.v2_credential(credential_type=credential_type,
                                    inputs=dict(not_a_field=123))
        desired = {'inputs': ["Additional properties are not allowed (u'not_a_field' was unexpected)"]}
        assert e.value.message == desired

    def test_non_boolean_input_for_boolean_field(self, factories):
        inputs = dict(fields=[dict(id='field', label='Field', type='boolean')])
        credential_type = factories.credential_type(inputs=inputs)

        with pytest.raises(exc.BadRequest) as e:
            factories.v2_credential(credential_type=credential_type,
                                    inputs=dict(field=123))
        assert e.value.message == {'inputs': {'field': ["123 is not of type u'boolean'"]}}

        with pytest.raises(exc.BadRequest) as e:
            factories.v2_credential(credential_type=credential_type,
                                    inputs=dict(field='string'))
        assert e.value.message == {'inputs': {'field': ["u'string' is not of type u'boolean'"]}}

    def test_extra_var_injector_variables_in_job_args_and_event_data(self, factories):
        inputs = dict(fields=[dict(id='field_one', label='FieldOne', secret=True),
                              dict(id='field_two', label='FieldTwo', type='string'),
                              dict(id='field_three', label='FieldThree', type='boolean'),
                              dict(id='field_four', label='FieldFour', type='boolean')])
        injectors = dict(extra_vars=dict(extra_var_from_field_one='{{ field_one }}',
                                         extra_var_from_field_two='{{ field_two }}',
                                         extra_var_from_field_three='{{ field_three }}',
                                         extra_var_from_field_four='{{ field_four }}'))
        credential_type = factories.credential_type(inputs=inputs, injectors=injectors)

        input_values = dict(field_one='FieldOneVal', field_two='True', field_three=False, field_four=True)
        field_to_var = dict(field_one='extra_var_from_field_one', field_two='extra_var_from_field_two',
                            field_three='extra_var_from_field_three', field_four='extra_var_from_field_four')
        credential = factories.v2_credential(credential_type=credential_type, inputs=input_values)

        host = factories.v2_host()
        jt = factories.v2_job_template(inventory=host.ds.inventory, playbook='debug_hostvars.yml')
        jt.add_extra_credential(credential)
        job = jt.launch().wait_until_completed()
        assert job.is_successful

        assert dict(extra_var_from_field_one='**********', extra_var_from_field_two='True',
                    extra_var_from_field_three='False', extra_var_from_field_four='True') in job.job_args

        hostvars = job.related.job_events.get(host=host.id, task='debug').results.pop().event_data.res.hostvars
        for field, value in input_values.items():
            assert hostvars[host.name][field_to_var[field]] == str(value)

    def test_env_var_injector_variables_in_job_env_and_ansible_env(self, factories):
        inputs = dict(fields=[dict(id='field_one', label='FieldOne', secret=True),
                              dict(id='field_two', label='FieldTwo', type='string'),
                              dict(id='field_three', label='FieldThree', type='boolean'),
                              dict(id='field_four', label='FieldFour', type='boolean')])
        injectors = dict(env=dict(EXTRA_VAR_FROM_FIELD_ONE='{{ field_one }}',
                                  EXTRA_VAR_FROM_FIELD_TWO='{{ field_two }}',
                                  EXTRA_VAR_FROM_FIELD_THREE='{{ field_three }}',
                                  EXTRA_VAR_FROM_FIELD_FOUR='{{ field_four }}'))
        credential_type = factories.credential_type(inputs=inputs, injectors=injectors)

        credential = factories.v2_credential(credential_type=credential_type,
                                             inputs=dict(field_one='FieldOneVal', field_two='True',
                                                         field_three=False, field_four=True))

        host = factories.v2_host()
        jt = factories.v2_job_template(inventory=host.ds.inventory, playbook='ansible_env.yml')
        jt.add_extra_credential(credential)
        job = jt.launch().wait_until_completed()
        assert job.is_successful

        assert job.job_env.EXTRA_VAR_FROM_FIELD_ONE == '**********'
        assert job.job_env.EXTRA_VAR_FROM_FIELD_TWO == 'True'
        assert job.job_env.EXTRA_VAR_FROM_FIELD_THREE == 'False'
        assert job.job_env.EXTRA_VAR_FROM_FIELD_FOUR == 'True'

        ansible_env = job.related.job_events.get(host=host.id, task='debug').results.pop().event_data.res.ansible_env
        assert ansible_env.EXTRA_VAR_FROM_FIELD_ONE == 'FieldOneVal'
        assert ansible_env.EXTRA_VAR_FROM_FIELD_TWO == 'True'
        assert ansible_env.EXTRA_VAR_FROM_FIELD_THREE == 'False'
        assert ansible_env.EXTRA_VAR_FROM_FIELD_FOUR == 'True'

    @pytest.mark.parametrize('injector_var',
                             [dict(extra_vars=dict(file_to_cat='{{ tower.filename }}')),
                              dict(env=dict(AP_FILE_TO_CAT='{{ tower.filename }}'))],
                             ids=('extra_var', 'env_var'))
    def test_file_injector_path_from_variable(self, factories, injector_var):
        file_contents = 'THIS IS A FILE!'
        injectors = dict(file=dict(template=file_contents))
        injectors.update(injector_var)
        credential_type = factories.credential_type(injectors=injectors)

        credential = factories.v2_credential(credential_type=credential_type)

        host = factories.v2_host()
        jt = factories.v2_job_template(inventory=host.ds.inventory, playbook='cat_file.yml')
        jt.add_extra_credential(credential)
        job = jt.launch().wait_until_completed()
        assert job.is_successful

        stdout = job.related.job_events.get(host=host.id, task='debug').results.pop().event_data.res.cat.stdout
        assert stdout == file_contents

    def test_credential_creation_and_usage_dont_leak_fields_into_activity_stream(self, factories):
        inputs = dict(fields=[dict(id='field_one', label='FieldOne', secret=True),
                              dict(id='field_two', label='FieldTwo', secret=True)])
        injectors = dict(env=dict(EXTRA_VAR_FROM_FIELD_ONE='{{ field_one }}',
                                  EXTRA_VAR_FROM_FIELD_TWO='{{ field_two }}'))
        credential_type = factories.credential_type(inputs=inputs, injectors=injectors)

        credential = factories.v2_credential(credential_type=credential_type,
                                             inputs=dict(field_one='FieldOneVal', field_two='FieldTwoVal'))

        host = factories.v2_host()
        jt = factories.v2_job_template(inventory=host.ds.inventory, playbook='ansible_env.yml')
        jt.add_extra_credential(credential)
        job = jt.launch().wait_until_completed()
        assert job.is_successful

        for stream_endpoint in (credential_type.related.activity_stream, credential.related.activity_stream,
                                jt.related.activity_stream, job.related.activity_stream):
            stream = to_str(stream_endpoint.get())
            for secret in ('FieldOneVal', 'FieldTwoVal', 'md5'):
                assert secret not in stream
