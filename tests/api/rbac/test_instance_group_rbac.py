import httplib
import random

from towerkit import utils
import towerkit.exceptions as exc
import pytest

from tests.lib.helpers.rbac_utils import assert_response_raised, check_read_access
from tests.api import Base_Api_Test


@pytest.mark.api
@pytest.mark.rbac
@pytest.mark.usefixtures('authtoken', 'install_enterprise_license_unlimited')
class TestInstanceGroupRBAC(Base_Api_Test):

    def test_unprivileged_user(self, v2, factories):
        """An unprivileged user should not be able to:
        * Create instance groups.
        * See instance groups.
        * Edit instance groups.
        * Delete instance groups.
        """
        ig = factories.instance_group()
        user = factories.v2_user()

        with self.current_user(user):
            with pytest.raises(exc.Forbidden):
                factories.instance_group()

            # check GET as test user
            check_read_access(ig, unprivileged=True)

            # check put/patch/delete
            assert_response_raised(ig, httplib.FORBIDDEN)

    def test_org_admin(self, v2, factories):
        """An organization admin should be able to:
        * See instance groups within his own organization.
        An organization admin should not be able to:
        * Create instance groups.
        * See instance groups outside of his organization.
        * Edit instance groups.
        * Delete intance groups.
        """
        ig = factories.instance_group()
        instance = random.sample(v2.instances.get().results, 1).pop()
        ig.add_instance(instance)

        excluded_ig = factories.instance_group()

        org = factories.v2_organization()
        org.add_instance_group(ig)
        user = factories.user()
        org.add_admin(user)

        with self.current_user(user):
            with pytest.raises(exc.Forbidden):
                factories.instance_group()

            # check GET as test user
            check_read_access(ig)
            check_read_access(excluded_ig, unprivileged=True)

            instances = v2.instances.get()
            assert instances.count == 1
            assert len(instances.results) == 1
            check_read_access(instance)

            # check put/patch/delete
            assert_response_raised(ig, httplib.FORBIDDEN)


@pytest.mark.api
@pytest.mark.rbac
@pytest.mark.usefixtures('authtoken', 'install_enterprise_license_unlimited')
class TestInstanceGroupAssignmentRBAC(Base_Api_Test):

    @pytest.mark.requires_ha
    @pytest.mark.parametrize('resource_type', ['job_template', 'inventory', 'organization'])
    def test_superuser(self, v2, factories, resource_type):
        """A superuser should be able to (un)assign any instance group to a resource."""
        resource = getattr(factories, resource_type)()
        assert resource.get_related('instance_groups').count == 0

        for ig in v2.instance_groups.get().results:
            resource.add_instance_group(ig)
            assert resource.get_related('instance_groups').count == 1
            assert resource.get_related('instance_groups').results.pop().id == ig.id
            resource.remove_instance_group(ig)
            assert resource.get_related('instance_groups').count == 0

    @pytest.mark.requires_traditional_ha
    @pytest.mark.parametrize('resource_type', ['job_template', 'inventory'])
    def test_org_admin(self, v2, factories, resource_type):
        """An org admin should only be able to (un)assign instance groups associated
        with their organization.
        """
        user = factories.user()
        resource = getattr(factories, resource_type)()
        resource.set_object_roles(user, 'admin')
        if resource_type == 'job_template':
            org = resource.ds.project.ds.organization
        else:
            org = resource.ds.organization
        org.add_admin(user)

        all_instance_groups = v2.instance_groups.get().results
        org_instance_groups = random.sample(all_instance_groups, 2)
        for ig in org_instance_groups:
            org.add_instance_group(ig)

        with self.current_user(username=user.username, password=user.password):
            for ig in all_instance_groups:
                if ig in org_instance_groups:
                    resource.add_instance_group(ig)
                else:
                    with pytest.raises(exc.Forbidden):
                        resource.add_instance_group(ig)
        assert resource.get_related('instance_groups').count == len(org_instance_groups)
        assert set([ig.id for ig in resource.get_related('instance_groups').results]) == set([ig.id for ig in org_instance_groups])

        for ig in all_instance_groups:
            if ig in org_instance_groups:
                with self.current_user(username=user.username, password=user.password):
                    resource.remove_instance_group(ig)
            else:
                resource.add_instance_group(ig)
                with self.current_user(username=user.username, password=user.password):
                    with pytest.raises(exc.Forbidden):
                        resource.remove_instance_group(ig)
        resource_instance_group_ids = set([ig.id for ig in resource.get_related('instance_groups').results])
        org_instance_group_ids = set([ig.id for ig in all_instance_groups if ig.id not in [org_ig.id for org_ig in org_instance_groups]])
        assert resource_instance_group_ids == org_instance_group_ids

    @pytest.mark.requires_traditional_ha
    def test_org_admin_managing_organization_instance_groups(self, v2, factories):
        """An org admin should not be able to (un)set instance groups on their own
        organization (or any other).
        """
        user = factories.user()
        org = factories.organization()
        org.add_admin(user)
        other_org = factories.organization()

        # Org admin cannot add instance groups to any org
        all_instance_groups = v2.instance_groups.get().results
        for ig in all_instance_groups:
            with self.current_user(username=user.username, password=user.password):
                with pytest.raises(exc.Forbidden):
                    org.add_instance_group(ig)
                with pytest.raises(exc.Forbidden):
                    other_org.add_instance_group(ig)
            assert org.get_related('instance_groups').count == 0
            assert other_org.get_related('instance_groups').count == 0

        org_instance_groups = random.sample(all_instance_groups, 2)
        for ig in org_instance_groups:
            org.add_instance_group(ig)
            other_org.add_instance_group(ig)

        assert org.get_related('instance_groups').count == len(org_instance_groups)
        assert other_org.get_related('instance_groups').count == len(org_instance_groups)
        assert set([ig.id for ig in org.get_related('instance_groups').results]) == set([ig.id for ig in org_instance_groups])
        assert set([ig.id for ig in other_org.get_related('instance_groups').results]) == set([ig.id for ig in org_instance_groups])

        # Org admin cannot remove instance groups from any org
        for ig in org_instance_groups:
            with self.current_user(username=user.username, password=user.password):
                with pytest.raises(exc.Forbidden):
                    org.remove_instance_group(ig)
                with pytest.raises(exc.Forbidden):
                    other_org.remove_instance_group(ig)
            assert org.get_related('instance_groups').count == len(org_instance_groups)
            assert other_org.get_related('instance_groups').count == len(org_instance_groups)

    @pytest.mark.requires_ha
    @pytest.mark.parametrize('resource_type', ['job_template', 'inventory', 'organization'])
    def test_regular_user(self, v2, factories, resource_type):
        """A regular user should not be able to (un)assign instance_groups to any resources"""
        user = factories.user()
        jt = factories.job_template()
        jt.set_object_roles(user, 'admin')

        instance_groups = v2.instance_groups.get().results
        with self.current_user(username=user.username, password=user.password):
            for ig in instance_groups:
                with pytest.raises(exc.Forbidden):
                    jt.add_instance_group(ig)
        assert jt.get_related('instance_groups').count == 0

        for ig in instance_groups:
            jt.add_instance_group(ig)
        with self.current_user(username=user.username, password=user.password):
            for ig in instance_groups:
                with pytest.raises(exc.Forbidden):
                    jt.remove_instance_group(ig)
        assert jt.get_related('instance_groups').count == len(instance_groups)

    def test_instance_assignment_and_unassignment_to_tower_ig_only_allowed_as_superuser(self, request, factories,
                                                                                        v2, tower_instance_group):
        tower_ig_instances = tower_instance_group.related.instances.get().results

        def teardown():
            for instance in tower_ig_instances:
                tower_instance_group.add_instance(instance)
        request.addfinalizer(teardown)

        user = factories.user()

        for instance in tower_ig_instances:
            tower_instance_group.remove_instance(instance)
        utils.poll_until(lambda: tower_instance_group.get().instances == 0, interval=1, timeout=30)

        for instance in tower_ig_instances:
            tower_instance_group.add_instance(instance)
        utils.poll_until(lambda: tower_instance_group.get().instances == len(tower_ig_instances), interval=1,
                                 timeout=30)

        with self.current_user(user):
            for instance in tower_ig_instances:
                with pytest.raises(exc.Forbidden):
                    tower_instance_group.remove_instance(instance)
                with pytest.raises(exc.Forbidden):
                    tower_instance_group.add_instance(instance)
