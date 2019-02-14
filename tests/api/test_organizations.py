import pytest
import towerkit.exceptions
from tests.api import APITest


@pytest.fixture(scope="function", params=['job_template',
                                          'check_job_template',
                                          'org_user',
                                          'team',
                                          'org_admin',
                                          'inventory',
                                          'project'])
def related_organization_object(request):
    """Create organization_related_counts objects sequentially."""
    return request.getfixturevalue(request.param)


@pytest.mark.api
@pytest.mark.destructive
@pytest.mark.usefixtures('authtoken', 'install_enterprise_license_unlimited')
class Test_Organizations(APITest):
    """Verify the /users endpoint displays the expected information based on the current user"""

    def test_duplicate_organizations_disallowed(self, factories):
        org = factories.v2_organization()
        with pytest.raises(towerkit.exceptions.Duplicate) as e:
            factories.v2_organization(name=org.name)
        assert e.value[1]['name'] == ['Organization with this Name already exists.']

    def test_delete(self, api_organizations_pg, organization):
        """Verify that deleting an organization actually works."""
        # Delete the organization
        organization.delete()

        # assert the organization was deleted
        matches = api_organizations_pg.get(id=organization.id)
        assert matches.count == 0, "An organization was deleted, but is still visible from the /api/v1/organizations/ endpoint"

    def test_organization_related_counts(self, organization, related_organization_object, api_job_templates_pg):
        """Verify summary_fields 'related_field_counts' content."""
        # determine the expected JTs count
        #
        # note: the API determines the organization of a non-scan JT by looking at the organization of the JT project. For scan JTs, it
        # looks at the organization of the JT inventory instead.
        inventory_pg = organization.get_related('inventories')
        org_inventory_ids = [inv_pg.id for inv_pg in inventory_pg.results]
        project_pg = organization.get_related('projects')
        org_project_ids = [proj_pg.id for proj_pg in project_pg.results]

        params = dict(job_type='scan', inventory__in=-1)
        if org_inventory_ids:
            params['inventory__in'] = ','.join(str(entry) for entry in org_inventory_ids)
        scan_job_templates_count = api_job_templates_pg.get(**params).count

        params = dict(not__job_type='scan', project__in=-1)
        if org_project_ids:
            params['project__in'] = ','.join(str(entry) for entry in org_project_ids)
        other_job_templates_count = api_job_templates_pg.get(**params).count

        # check related_field_counts
        # note: there is no 'job_templates' get_related field so we handle job_templates differently
        related_field_counts = organization.get().summary_fields['related_field_counts']
        for key in related_field_counts.keys():
            if key != 'job_templates':
                assert related_field_counts[key] == organization.get_related(key).count, \
                    "Incorrect value for %s. Expected %s, got %s." % (key, organization.get_related(key).count, related_field_counts[key])

        job_templates_count = scan_job_templates_count + other_job_templates_count
        assert job_templates_count == related_field_counts['job_templates'], \
            "Incorrect value for job_templates. Expected %s, got %s." % (job_templates_count, related_field_counts['job_templates'])

    def test_organization_host_limits_do_not_allow_adding_too_many_hosts(self, factories):
        org = factories.v2_organization()
        org.max_hosts = 2
        inv = factories.v2_inventory(organization=org)
        [inv.add_host() for _ in range(2)]
        with pytest.raises(towerkit.exceptions.Forbidden) as e:
            inv.add_host()
        assert e.value.msg['detail'] == 'The organization host limit has been exceeded.'

    def test_organization_host_limits_apply_across_all_inventories(self, factories):
        org = factories.v2_organization()
        org.max_hosts = 2
        inv = factories.v2_inventory(organization=org)
        [inv.add_host() for _ in range(2)]
        inv2 = factories.v2_inventory(organization=org)
        with pytest.raises(towerkit.exceptions.Forbidden) as e:
            inv2.add_host()
        assert e.value.msg['detail'] == 'The organization host limit has been exceeded.'

    def test_organization_host_limits_no_longer_apply_to_inventory_if_org_changed(self, factories):
        org = factories.v2_organization()
        org2 = factories.v2_organization()
        org.max_hosts = 2
        inv = factories.v2_inventory(organization=org)
        [inv.add_host() for _ in range(2)]
        inv.patch(organization=org2.id)
        inv.add_host()
        assert inv.get().total_hosts == 3
