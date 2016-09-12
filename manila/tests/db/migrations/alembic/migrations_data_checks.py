# Copyright 2015 Mirantis inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Tests data for database migrations.

All database migrations with data manipulation
(like moving data from column to the table) should have data check class:

@map_to_migration('1f0bd302c1a6') # Revision of checked db migration
class FooMigrationChecks(BaseMigrationChecks):
   def setup_upgrade_data(self, engine):
       ...

    def check_upgrade(self, engine, data):
       ...

    def check_downgrade(self, engine):
       ...

See BaseMigrationChecks class for more information.
"""

import abc
import datetime

from oslo_utils import uuidutils
import six
from sqlalchemy import exc as sa_exc

from manila.db.migrations import utils


class DbMigrationsData(object):

    migration_mappings = {}

    methods_mapping = {
        'pre': 'setup_upgrade_data',
        'check': 'check_upgrade',
        'post': 'check_downgrade',
    }

    def __getattr__(self, item):
        parts = item.split('_')

        is_mapping_method = (
            len(parts) > 2 and parts[0] == ''
            and parts[1] in self.methods_mapping
        )

        if not is_mapping_method:
            return super(DbMigrationsData, self).__getattribute__(item)

        check_obj = self.migration_mappings.get(parts[-1], None)

        if check_obj is None:
            raise AttributeError

        check_obj.set_test_case(self)

        return getattr(check_obj, self.methods_mapping.get(parts[1]))


def map_to_migration(revision):
    def decorator(cls):
        DbMigrationsData.migration_mappings[revision] = cls()
        return cls
    return decorator


class BaseMigrationChecks(object):

    six.add_metaclass(abc.ABCMeta)

    def __init__(self):
        self.test_case = None

    def set_test_case(self, test_case):
        self.test_case = test_case

    @abc.abstractmethod
    def setup_upgrade_data(self, engine):
        """This method should be used to insert test data for migration.

        :param engine: SQLAlchemy engine
        :return: any data which will be passed to 'check_upgrade' as 'data' arg
        """

    @abc.abstractmethod
    def check_upgrade(self, engine, data):
        """This method should be used to do assertions after upgrade method.

        To perform assertions use 'self.test_case' instance property:
        self.test_case.assertTrue(True)

        :param engine: SQLAlchemy engine
        :param data: data returned by 'setup_upgrade_data'
        """

    @abc.abstractmethod
    def check_downgrade(self, engine):
        """This method should be used to do assertions after downgrade method.

        To perform assertions use 'self.test_case' instance property:
        self.test_case.assertTrue(True)

        :param engine: SQLAlchemy engine
        """


@map_to_migration('1f0bd302c1a6')
class AvailabilityZoneMigrationChecks(BaseMigrationChecks):

    valid_az_names = ('az1', 'az2')

    def _get_service_data(self, options):
        base_dict = {
            'binary': 'manila-share',
            'topic': 'share',
            'disabled': '0',
            'report_count': '100',
        }
        base_dict.update(options)
        return base_dict

    def setup_upgrade_data(self, engine):
        service_fixture = [
            self._get_service_data(
                {'deleted': 0, 'host': 'fake1', 'availability_zone': 'az1'}
            ),
            self._get_service_data(
                {'deleted': 0, 'host': 'fake2', 'availability_zone': 'az1'}
            ),
            self._get_service_data(
                {'deleted': 1, 'host': 'fake3', 'availability_zone': 'az2'}
            ),
        ]

        services_table = utils.load_table('services', engine)

        for fixture in service_fixture:
            engine.execute(services_table.insert(fixture))

    def check_upgrade(self, engine, _):
        az_table = utils.load_table('availability_zones', engine)

        for az in engine.execute(az_table.select()):
            self.test_case.assertTrue(uuidutils.is_uuid_like(az.id))
            self.test_case.assertIn(az.name, self.valid_az_names)
            self.test_case.assertEqual('False', az.deleted)

        services_table = utils.load_table('services', engine)
        for service in engine.execute(services_table.select()):
            self.test_case.assertTrue(
                uuidutils.is_uuid_like(service.availability_zone_id)
            )

    def check_downgrade(self, engine):
        services_table = utils.load_table('services', engine)
        for service in engine.execute(services_table.select()):
            self.test_case.assertIn(
                service.availability_zone, self.valid_az_names
            )


@map_to_migration('dda6de06349')
class ShareInstanceExportLocationMetadataChecks(BaseMigrationChecks):
    el_table_name = 'share_instance_export_locations'
    elm_table_name = 'share_instance_export_locations_metadata'

    def setup_upgrade_data(self, engine):
        # Setup shares
        share_fixture = [{'id': 'foo_share_id'}, {'id': 'bar_share_id'}]
        share_table = utils.load_table('shares', engine)
        for fixture in share_fixture:
            engine.execute(share_table.insert(fixture))

        # Setup share instances
        si_fixture = [
            {'id': 'foo_share_instance_id_oof',
             'share_id': share_fixture[0]['id']},
            {'id': 'bar_share_instance_id_rab',
             'share_id': share_fixture[1]['id']},
        ]
        si_table = utils.load_table('share_instances', engine)
        for fixture in si_fixture:
            engine.execute(si_table.insert(fixture))

        # Setup export locations
        el_fixture = [
            {'id': 1, 'path': '/1', 'share_instance_id': si_fixture[0]['id']},
            {'id': 2, 'path': '/2', 'share_instance_id': si_fixture[1]['id']},
        ]
        el_table = utils.load_table(self.el_table_name, engine)
        for fixture in el_fixture:
            engine.execute(el_table.insert(fixture))

    def check_upgrade(self, engine, data):
        el_table = utils.load_table(
            'share_instance_export_locations', engine)
        for el in engine.execute(el_table.select()):
            self.test_case.assertTrue(hasattr(el, 'is_admin_only'))
            self.test_case.assertTrue(hasattr(el, 'uuid'))
            self.test_case.assertEqual(False, el.is_admin_only)
            self.test_case.assertTrue(uuidutils.is_uuid_like(el.uuid))

        # Write export location metadata
        el_metadata = [
            {'key': 'foo_key', 'value': 'foo_value', 'export_location_id': 1},
            {'key': 'bar_key', 'value': 'bar_value', 'export_location_id': 2},
        ]
        elm_table = utils.load_table(self.elm_table_name, engine)
        engine.execute(elm_table.insert(el_metadata))

        # Verify values of written metadata
        for el_meta_datum in el_metadata:
            el_id = el_meta_datum['export_location_id']
            records = engine.execute(elm_table.select().where(
                elm_table.c.export_location_id == el_id))
            self.test_case.assertEqual(1, records.rowcount)
            record = records.first()

            expected_keys = (
                'id', 'created_at', 'updated_at', 'deleted_at', 'deleted',
                'export_location_id', 'key', 'value',
            )
            self.test_case.assertEqual(len(expected_keys), len(record.keys()))
            for key in expected_keys:
                self.test_case.assertIn(key, record.keys())

            for k, v in el_meta_datum.items():
                self.test_case.assertTrue(hasattr(record, k))
                self.test_case.assertEqual(v, getattr(record, k))

    def check_downgrade(self, engine):
        el_table = utils.load_table(
            'share_instance_export_locations', engine)
        for el in engine.execute(el_table.select()):
            self.test_case.assertFalse(hasattr(el, 'is_admin_only'))
            self.test_case.assertFalse(hasattr(el, 'uuid'))
        self.test_case.assertRaises(
            sa_exc.NoSuchTableError,
            utils.load_table, self.elm_table_name, engine)


@map_to_migration('344c1ac4747f')
class AccessRulesStatusMigrationChecks(BaseMigrationChecks):

    def _get_instance_data(self, data):
        base_dict = {}
        base_dict.update(data)
        return base_dict

    def setup_upgrade_data(self, engine):

        share_table = utils.load_table('shares', engine)

        share = {
            'id': 1,
            'share_proto': "NFS",
            'size': 0,
            'snapshot_id': None,
            'user_id': 'fake',
            'project_id': 'fake',
        }

        engine.execute(share_table.insert(share))

        rules1 = [
            {'id': 'r1', 'share_instance_id': 1, 'state': 'active',
             'deleted': 'False'},
            {'id': 'r2', 'share_instance_id': 1, 'state': 'active',
             'deleted': 'False'},
            {'id': 'r3', 'share_instance_id': 1, 'state': 'deleting',
             'deleted': 'False'},
        ]
        rules2 = [
            {'id': 'r4', 'share_instance_id': 2, 'state': 'active',
             'deleted': 'False'},
            {'id': 'r5', 'share_instance_id': 2, 'state': 'error',
             'deleted': 'False'},
        ]

        rules3 = [
            {'id': 'r6', 'share_instance_id': 3, 'state': 'new',
             'deleted': 'False'},
        ]

        instance_fixtures = [
            {'id': 1, 'deleted': 'False', 'host': 'fake1', 'share_id': 1,
             'status': 'available', 'rules': rules1},
            {'id': 2, 'deleted': 'False', 'host': 'fake2', 'share_id': 1,
             'status': 'available', 'rules': rules2},
            {'id': 3, 'deleted': 'False', 'host': 'fake3', 'share_id': 1,
             'status': 'available', 'rules': rules3},
            {'id': 4, 'deleted': 'False', 'host': 'fake4', 'share_id': 1,
             'status': 'deleting', 'rules': []},
        ]

        share_instances_table = utils.load_table('share_instances', engine)
        share_instances_rules_table = utils.load_table(
            'share_instance_access_map', engine)

        for fixture in instance_fixtures:
            rules = fixture.pop('rules')
            engine.execute(share_instances_table.insert(fixture))

            for rule in rules:
                engine.execute(share_instances_rules_table.insert(rule))

    def check_upgrade(self, engine, _):
        instances_table = utils.load_table('share_instances', engine)

        valid_statuses = {
            '1': 'active',
            '2': 'error',
            '3': 'out_of_sync',
            '4': None,
        }

        instances = engine.execute(instances_table.select().where(
            instances_table.c.id in valid_statuses.keys()))

        for instance in instances:
            self.test_case.assertEqual(valid_statuses[instance['id']],
                                       instance['access_rules_status'])

    def check_downgrade(self, engine):
        share_instances_rules_table = utils.load_table(
            'share_instance_access_map', engine)

        valid_statuses = {
            '1': 'active',
            '2': 'error',
            '3': 'error',
            '4': None,
        }

        for rule in engine.execute(share_instances_rules_table.select()):
            valid_state = valid_statuses[rule['share_instance_id']]
            self.test_case.assertEqual(valid_state, rule['state'])


@map_to_migration('293fac1130ca')
class ShareReplicationMigrationChecks(BaseMigrationChecks):

    valid_share_display_names = ('FAKE_SHARE_1', 'FAKE_SHARE_2',
                                 'FAKE_SHARE_3')
    valid_share_ids = []
    valid_replication_types = ('writable', 'readable', 'dr')

    def _load_tables_and_get_data(self, engine):
        share_table = utils.load_table('shares', engine)
        share_instances_table = utils.load_table('share_instances', engine)

        shares = engine.execute(
            share_table.select().where(share_table.c.id.in_(
                self.valid_share_ids))
        ).fetchall()
        share_instances = engine.execute(share_instances_table.select().where(
            share_instances_table.c.share_id.in_(self.valid_share_ids))
        ).fetchall()

        return shares, share_instances

    def _new_share(self, **kwargs):
        share = {
            'id': uuidutils.generate_uuid(),
            'display_name': 'fake_share',
            'size': '1',
            'deleted': 'False',
            'share_proto': 'fake_proto',
            'user_id': 'fake_user_id',
            'project_id': 'fake_project_uuid',
            'snapshot_support': '1',
            'task_state': None,
        }
        share.update(kwargs)
        return share

    def _new_instance(self, share_id=None, **kwargs):
        instance = {
            'id': uuidutils.generate_uuid(),
            'share_id': share_id or uuidutils.generate_uuid(),
            'deleted': 'False',
            'host': 'openstack@BackendZ#PoolA',
            'status': 'available',
            'scheduled_at': datetime.datetime(2015, 8, 10, 0, 5, 58),
            'launched_at': datetime.datetime(2015, 8, 10, 0, 5, 58),
            'terminated_at': None,
            'access_rules_status': 'active',
        }
        instance.update(kwargs)
        return instance

    def setup_upgrade_data(self, engine):

        shares_data = []
        instances_data = []
        self.valid_share_ids = []

        for share_display_name in self.valid_share_display_names:
            share_ref = self._new_share(display_name=share_display_name)
            shares_data.append(share_ref)
            instances_data.append(self._new_instance(share_id=share_ref['id']))

        shares_table = utils.load_table('shares', engine)

        for share in shares_data:
            self.valid_share_ids.append(share['id'])
            engine.execute(shares_table.insert(share))

        shares_instances_table = utils.load_table('share_instances', engine)

        for share_instance in instances_data:
            engine.execute(shares_instances_table.insert(share_instance))

    def check_upgrade(self, engine, _):
        shares, share_instances = self._load_tables_and_get_data(engine)
        share_ids = [share['id'] for share in shares]
        share_instance_share_ids = [share_instance['share_id'] for
                                    share_instance in share_instances]

        # Assert no data is lost
        for sid in self.valid_share_ids:
            self.test_case.assertIn(sid, share_ids)
            self.test_case.assertIn(sid, share_instance_share_ids)

        for share in shares:
            self.test_case.assertIn(share['display_name'],
                                    self.valid_share_display_names)
            self.test_case.assertEqual('False', share.deleted)
            self.test_case.assertTrue(hasattr(share, 'replication_type'))

        for share_instance in share_instances:
            self.test_case.assertTrue(hasattr(share_instance, 'replica_state'))

    def check_downgrade(self, engine):
        shares, share_instances = self._load_tables_and_get_data(engine)
        share_ids = [share['id'] for share in shares]
        share_instance_share_ids = [share_instance['share_id'] for
                                    share_instance in share_instances]
        # Assert no data is lost
        for sid in self.valid_share_ids:
            self.test_case.assertIn(sid, share_ids)
            self.test_case.assertIn(sid, share_instance_share_ids)

        for share in shares:
            self.test_case.assertEqual('False', share.deleted)
            self.test_case.assertIn(share.display_name,
                                    self.valid_share_display_names)
            self.test_case.assertFalse(hasattr(share, 'replication_type'))

        for share_instance in share_instances:
            self.test_case.assertEqual('False', share_instance.deleted)
            self.test_case.assertIn(share_instance.share_id,
                                    self.valid_share_ids)
            self.test_case.assertFalse(
                hasattr(share_instance, 'replica_state'))


@map_to_migration('5155c7077f99')
class NetworkAllocationsNewLabelColumnChecks(BaseMigrationChecks):
    table_name = 'network_allocations'
    ids = ['fake_network_allocation_id_%d' % i for i in (1, 2, 3)]

    def setup_upgrade_data(self, engine):
        user_id = 'user_id'
        project_id = 'project_id'
        share_server_id = 'foo_share_server_id'

        # Create share network
        share_network_data = {
            'id': 'foo_share_network_id',
            'user_id': user_id,
            'project_id': project_id,
        }
        sn_table = utils.load_table('share_networks', engine)
        engine.execute(sn_table.insert(share_network_data))

        # Create share server
        share_server_data = {
            'id': share_server_id,
            'share_network_id': share_network_data['id'],
            'host': 'fake_host',
            'status': 'active',
        }
        ss_table = utils.load_table('share_servers', engine)
        engine.execute(ss_table.insert(share_server_data))

        # Create network allocations
        network_allocations = [
            {'id': self.ids[0],
             'share_server_id': share_server_id,
             'ip_address': '1.1.1.1'},
            {'id': self.ids[1],
             'share_server_id': share_server_id,
             'ip_address': '2.2.2.2'},
        ]
        na_table = utils.load_table(self.table_name, engine)
        for network_allocation in network_allocations:
            engine.execute(na_table.insert(network_allocation))

    def check_upgrade(self, engine, data):
        na_table = utils.load_table(self.table_name, engine)
        for na in engine.execute(na_table.select()):
            self.test_case.assertTrue(hasattr(na, 'label'))
            self.test_case.assertEqual(na.label, 'user')

        # Create admin network allocation
        network_allocations = [
            {'id': self.ids[2],
             'share_server_id': na.share_server_id,
             'ip_address': '3.3.3.3',
             'label': 'admin',
             'network_type': 'vlan',
             'segmentation_id': 1005,
             'ip_version': 4,
             'cidr': '240.0.0.0/16'},
        ]
        engine.execute(na_table.insert(network_allocations))

        # Select admin network allocations
        for na in engine.execute(
                na_table.select().where(na_table.c.label == 'admin')):
            self.test_case.assertTrue(hasattr(na, 'label'))
            self.test_case.assertEqual('admin', na.label)
            for col_name in ('network_type', 'segmentation_id', 'ip_version',
                             'cidr'):
                self.test_case.assertTrue(hasattr(na, col_name))
                self.test_case.assertEqual(
                    network_allocations[0][col_name], getattr(na, col_name))

    def check_downgrade(self, engine):
        na_table = utils.load_table(self.table_name, engine)
        db_result = engine.execute(na_table.select())
        self.test_case.assertTrue(db_result.rowcount >= len(self.ids))
        for na in db_result:
            for col_name in ('label', 'network_type', 'segmentation_id',
                             'ip_version', 'cidr'):
                self.test_case.assertFalse(hasattr(na, col_name))


@map_to_migration('eb6d5544cbbd')
class ShareSnapshotInstanceNewProviderLocationColumnChecks(
        BaseMigrationChecks):
    table_name = 'share_snapshot_instances'

    def setup_upgrade_data(self, engine):
        # Setup shares
        share_data = {'id': 'new_share_id'}
        s_table = utils.load_table('shares', engine)
        engine.execute(s_table.insert(share_data))

        # Setup share instances
        share_instance_data = {
            'id': 'new_share_instance_id',
            'share_id': share_data['id']
        }
        si_table = utils.load_table('share_instances', engine)
        engine.execute(si_table.insert(share_instance_data))

        # Setup share snapshots
        share_snapshot_data = {
            'id': 'new_snapshot_id',
            'share_id': share_data['id']}
        snap_table = utils.load_table('share_snapshots', engine)
        engine.execute(snap_table.insert(share_snapshot_data))

        # Setup snapshot instances
        snapshot_instance_data = {
            'id': 'new_snapshot_instance_id',
            'snapshot_id': share_snapshot_data['id'],
            'share_instance_id': share_instance_data['id']
        }
        snap_i_table = utils.load_table('share_snapshot_instances', engine)
        engine.execute(snap_i_table.insert(snapshot_instance_data))

    def check_upgrade(self, engine, data):
        ss_table = utils.load_table(self.table_name, engine)
        db_result = engine.execute(ss_table.select())
        self.test_case.assertTrue(db_result.rowcount > 0)
        for ss in db_result:
            self.test_case.assertTrue(hasattr(ss, 'provider_location'))
            self.test_case.assertEqual('new_snapshot_instance_id', ss.id)
            self.test_case.assertEqual('new_snapshot_id', ss.snapshot_id)

    def check_downgrade(self, engine):
        ss_table = utils.load_table(self.table_name, engine)
        db_result = engine.execute(ss_table.select())
        self.test_case.assertTrue(db_result.rowcount > 0)
        for ss in db_result:
            self.test_case.assertFalse(hasattr(ss, 'provider_location'))
            self.test_case.assertEqual('new_snapshot_instance_id', ss.id)
            self.test_case.assertEqual('new_snapshot_id', ss.snapshot_id)


@map_to_migration('221a83cfd85b')
class ShareNetwoksFieldLengthChecks(BaseMigrationChecks):
    def setup_upgrade_data(self, engine):
        user_id = '123456789123456789'
        project_id = 'project_id'

        # Create share network data
        share_network_data = {
            'id': 'foo_share_network_id_2',
            'user_id': user_id,
            'project_id': project_id,
        }
        sn_table = utils.load_table('share_networks', engine)
        engine.execute(sn_table.insert(share_network_data))

        # Create security_service data
        security_services_data = {
            'id': 'foo_security_services_id',
            'type': 'foo_type',
            'project_id': project_id
        }
        ss_table = utils.load_table('security_services', engine)
        engine.execute(ss_table.insert(security_services_data))

    def _check_length_for_table_columns(self, table_name, engine,
                                        cols, length):
        table = utils.load_table(table_name, engine)
        db_result = engine.execute(table.select())
        self.test_case.assertTrue(db_result.rowcount > 0)

        for col in cols:
            self.test_case.assertEqual(table.columns.get(col).type.length,
                                       length)

    def check_upgrade(self, engine, data):
        self._check_length_for_table_columns('share_networks', engine,
                                             ('user_id', 'project_id'), 255)

        self._check_length_for_table_columns('security_services', engine,
                                             ('project_id',), 255)

    def check_downgrade(self, engine):
        self._check_length_for_table_columns('share_networks', engine,
                                             ('user_id', 'project_id'), 36)

        self._check_length_for_table_columns('security_services', engine,
                                             ('project_id',), 36)


@map_to_migration('fdfb668d19e1')
class NewGatewayColumnChecks(BaseMigrationChecks):
    na_table_name = 'network_allocations'
    sn_table_name = 'share_networks'
    na_ids = ['network_allocation_id_fake_%d' % i for i in (1, 2, 3)]
    sn_ids = ['share_network_id_fake_%d' % i for i in (1, 2)]

    def setup_upgrade_data(self, engine):
        user_id = 'user_id'
        project_id = 'project_id'
        share_server_id = 'share_server_id_foo'

        # Create share network
        share_network_data = {
            'id': self.sn_ids[0],
            'user_id': user_id,
            'project_id': project_id,
        }
        sn_table = utils.load_table(self.sn_table_name, engine)
        engine.execute(sn_table.insert(share_network_data))

        # Create share server
        share_server_data = {
            'id': share_server_id,
            'share_network_id': share_network_data['id'],
            'host': 'fake_host',
            'status': 'active',
        }
        ss_table = utils.load_table('share_servers', engine)
        engine.execute(ss_table.insert(share_server_data))

        # Create network allocations
        network_allocations = [
            {
                'id': self.na_ids[0],
                'share_server_id': share_server_id,
                'ip_address': '1.1.1.1',
            },
            {
                'id': self.na_ids[1],
                'share_server_id': share_server_id,
                'ip_address': '2.2.2.2',
            },
        ]
        na_table = utils.load_table(self.na_table_name, engine)
        engine.execute(na_table.insert(network_allocations))

    def check_upgrade(self, engine, data):
        na_table = utils.load_table(self.na_table_name, engine)
        for na in engine.execute(na_table.select()):
            self.test_case.assertTrue(hasattr(na, 'gateway'))

        # Create network allocation
        network_allocations = [
            {
                'id': self.na_ids[2],
                'share_server_id': na.share_server_id,
                'ip_address': '3.3.3.3',
                'gateway': '3.3.3.1',
                'network_type': 'vlan',
                'segmentation_id': 1005,
                'ip_version': 4,
                'cidr': '240.0.0.0/16',
            },
        ]
        engine.execute(na_table.insert(network_allocations))

        # Select network allocations with gateway info
        for na in engine.execute(
                na_table.select().where(na_table.c.gateway == '3.3.3.1')):
            self.test_case.assertTrue(hasattr(na, 'gateway'))
            self.test_case.assertEqual(network_allocations[0]['gateway'],
                                       getattr(na, 'gateway'))

        sn_table = utils.load_table(self.sn_table_name, engine)
        for sn in engine.execute(sn_table.select()):
            self.test_case.assertTrue(hasattr(sn, 'gateway'))

        # Create share network
        share_networks = [
            {
                'id': self.sn_ids[1],
                'user_id': sn.user_id,
                'project_id': sn.project_id,
                'gateway': '1.1.1.1',
                'name': 'name_foo',
            },
        ]
        engine.execute(sn_table.insert(share_networks))

        # Select share network
        for sn in engine.execute(
                sn_table.select().where(sn_table.c.name == 'name_foo')):
            self.test_case.assertTrue(hasattr(sn, 'gateway'))
            self.test_case.assertEqual(share_networks[0]['gateway'],
                                       getattr(sn, 'gateway'))

    def check_downgrade(self, engine):
        for table_name, ids in ((self.na_table_name, self.na_ids),
                                (self.sn_table_name, self.sn_ids)):
            table = utils.load_table(table_name, engine)
            db_result = engine.execute(table.select())
            self.test_case.assertTrue(db_result.rowcount >= len(ids))
            for record in db_result:
                self.test_case.assertFalse(hasattr(record, 'gateway'))


@map_to_migration('e8ea58723178')
class RemoveHostFromDriverPrivateDataChecks(BaseMigrationChecks):
    table_name = 'drivers_private_data'
    host_column_name = 'host'

    def setup_upgrade_data(self, engine):
        dpd_data = {
            'created_at': datetime.datetime(2016, 7, 14, 22, 31, 22),
            'deleted': 0,
            'host': 'host1',
            'entity_uuid': 'entity_uuid1',
            'key': 'key1',
            'value': 'value1'
        }
        dpd_table = utils.load_table(self.table_name, engine)
        engine.execute(dpd_table.insert(dpd_data))

    def check_upgrade(self, engine, data):
        dpd_table = utils.load_table(self.table_name, engine)
        rows = engine.execute(dpd_table.select())
        for row in rows:
            self.test_case.assertFalse(hasattr(row, self.host_column_name))

    def check_downgrade(self, engine):
        dpd_table = utils.load_table(self.table_name, engine)
        rows = engine.execute(dpd_table.select())
        for row in rows:
            self.test_case.assertTrue(hasattr(row, self.host_column_name))
            self.test_case.assertEqual('unknown', row[self.host_column_name])


@map_to_migration('493eaffd79e1')
class NewMTUColumnChecks(BaseMigrationChecks):
    na_table_name = 'network_allocations'
    sn_table_name = 'share_networks'
    na_ids = ['network_allocation_id_fake_3_%d' % i for i in (1, 2, 3)]
    sn_ids = ['share_network_id_fake_3_%d' % i for i in (1, 2)]

    def setup_upgrade_data(self, engine):
        user_id = 'user_id'
        project_id = 'project_id'
        share_server_id = 'share_server_id_foo_2'

        # Create share network
        share_network_data = {
            'id': self.sn_ids[0],
            'user_id': user_id,
            'project_id': project_id,
        }
        sn_table = utils.load_table(self.sn_table_name, engine)
        engine.execute(sn_table.insert(share_network_data))

        # Create share server
        share_server_data = {
            'id': share_server_id,
            'share_network_id': share_network_data['id'],
            'host': 'fake_host',
            'status': 'active',
        }
        ss_table = utils.load_table('share_servers', engine)
        engine.execute(ss_table.insert(share_server_data))

        # Create network allocations
        network_allocations = [
            {
                'id': self.na_ids[0],
                'share_server_id': share_server_id,
                'ip_address': '1.1.1.1',
            },
            {
                'id': self.na_ids[1],
                'share_server_id': share_server_id,
                'ip_address': '2.2.2.2',
            },
        ]
        na_table = utils.load_table(self.na_table_name, engine)
        engine.execute(na_table.insert(network_allocations))

    def check_upgrade(self, engine, data):
        na_table = utils.load_table(self.na_table_name, engine)
        for na in engine.execute(na_table.select()):
            self.test_case.assertTrue(hasattr(na, 'mtu'))

        # Create network allocation
        network_allocations = [
            {
                'id': self.na_ids[2],
                'share_server_id': na.share_server_id,
                'ip_address': '3.3.3.3',
                'gateway': '3.3.3.1',
                'network_type': 'vlan',
                'segmentation_id': 1005,
                'ip_version': 4,
                'cidr': '240.0.0.0/16',
                'mtu': 1509,
            },
        ]
        engine.execute(na_table.insert(network_allocations))

        # Select network allocations with mtu info
        for na in engine.execute(
                na_table.select().where(na_table.c.mtu == '1509')):
            self.test_case.assertTrue(hasattr(na, 'mtu'))
            self.test_case.assertEqual(network_allocations[0]['mtu'],
                                       getattr(na, 'mtu'))

        # Select all entries and check for the value
        for na in engine.execute(na_table.select()):
            self.test_case.assertTrue(hasattr(na, 'mtu'))
            if na['id'] == self.na_ids[2]:
                self.test_case.assertEqual(network_allocations[0]['mtu'],
                                           getattr(na, 'mtu'))
            else:
                self.test_case.assertIsNone(na['mtu'])

        sn_table = utils.load_table(self.sn_table_name, engine)
        for sn in engine.execute(sn_table.select()):
            self.test_case.assertTrue(hasattr(sn, 'mtu'))

        # Create share network
        share_networks = [
            {
                'id': self.sn_ids[1],
                'user_id': sn.user_id,
                'project_id': sn.project_id,
                'gateway': '1.1.1.1',
                'name': 'name_foo_2',
                'mtu': 1509,
            },
        ]
        engine.execute(sn_table.insert(share_networks))

        # Select share network with MTU set
        for sn in engine.execute(
                sn_table.select().where(sn_table.c.name == 'name_foo_2')):
            self.test_case.assertTrue(hasattr(sn, 'mtu'))
            self.test_case.assertEqual(share_networks[0]['mtu'],
                                       getattr(sn, 'mtu'))

        # Select all entries and check for the value
        for sn in engine.execute(sn_table.select()):
            self.test_case.assertTrue(hasattr(sn, 'mtu'))
            if sn['id'] == self.sn_ids[1]:
                self.test_case.assertEqual(network_allocations[0]['mtu'],
                                           getattr(sn, 'mtu'))
            else:
                self.test_case.assertIsNone(sn['mtu'])

    def check_downgrade(self, engine):
        for table_name, ids in ((self.na_table_name, self.na_ids),
                                (self.sn_table_name, self.sn_ids)):
            table = utils.load_table(table_name, engine)
            db_result = engine.execute(table.select())
            self.test_case.assertTrue(db_result.rowcount >= len(ids))
            for record in db_result:
                self.test_case.assertFalse(hasattr(record, 'mtu'))


@map_to_migration('63809d875e32')
class AddAccessKeyToShareAccessMapping(BaseMigrationChecks):
    table_name = 'share_access_map'
    access_key_column_name = 'access_key'

    def setup_upgrade_data(self, engine):
        share_data = {
            'id': uuidutils.generate_uuid(),
            'share_proto': "CEPHFS",
            'size': 1,
            'snapshot_id': None,
            'user_id': 'fake',
            'project_id': 'fake'
        }
        share_table = utils.load_table('shares', engine)
        engine.execute(share_table.insert(share_data))

        share_instance_data = {
            'id': uuidutils.generate_uuid(),
            'deleted': 'False',
            'host': 'fake',
            'share_id': share_data['id'],
            'status': 'available',
            'access_rules_status': 'active'
        }
        share_instance_table = utils.load_table('share_instances', engine)
        engine.execute(share_instance_table.insert(share_instance_data))

        share_access_data = {
            'id': uuidutils.generate_uuid(),
            'share_id': share_data['id'],
            'access_type': 'cephx',
            'access_to': 'alice',
            'deleted': 'False'
        }
        share_access_table = utils.load_table(self.table_name, engine)
        engine.execute(share_access_table.insert(share_access_data))

        share_instance_access_data = {
            'id': uuidutils.generate_uuid(),
            'share_instance_id': share_instance_data['id'],
            'access_id': share_access_data['id'],
            'deleted': 'False'
        }
        share_instance_access_table = utils.load_table(
            'share_instance_access_map', engine)
        engine.execute(share_instance_access_table.insert(
            share_instance_access_data))

    def check_upgrade(self, engine, data):
        share_access_table = utils.load_table(self.table_name, engine)
        rows = engine.execute(share_access_table.select())
        for row in rows:
            self.test_case.assertTrue(hasattr(row,
                                              self.access_key_column_name))

    def check_downgrade(self, engine):
        share_access_table = utils.load_table(self.table_name, engine)
        rows = engine.execute(share_access_table.select())
        for row in rows:
            self.test_case.assertFalse(hasattr(row,
                                               self.access_key_column_name))


@map_to_migration('48a7beae3117')
class MoveShareTypeIdToInstancesCheck(BaseMigrationChecks):

    some_shares = [
        {
            'id': 's1',
            'share_type_id': 't1',
        },
        {
            'id': 's2',
            'share_type_id': 't2',
        },
        {
            'id': 's3',
            'share_type_id': 't3',
        },
    ]

    share_ids = [x['id'] for x in some_shares]

    some_instances = [
        {
            'id': 'i1',
            'share_id': 's3',
        },
        {
            'id': 'i2',
            'share_id': 's2',
        },
        {
            'id': 'i3',
            'share_id': 's2',
        },
        {
            'id': 'i4',
            'share_id': 's1',
        },
    ]

    instance_ids = [x['id'] for x in some_instances]

    some_share_types = [
        {'id': 't1'},
        {'id': 't2'},
        {'id': 't3'},
    ]

    def setup_upgrade_data(self, engine):

        shares_table = utils.load_table('shares', engine)
        share_instances_table = utils.load_table('share_instances', engine)
        share_types_table = utils.load_table('share_types', engine)

        for stype in self.some_share_types:
            engine.execute(share_types_table.insert(stype))

        for share in self.some_shares:
            engine.execute(shares_table.insert(share))

        for instance in self.some_instances:
            engine.execute(share_instances_table.insert(instance))

    def check_upgrade(self, engine, data):

        shares_table = utils.load_table('shares', engine)
        share_instances_table = utils.load_table('share_instances', engine)

        for instance in engine.execute(share_instances_table.select().where(
                share_instances_table.c.id in self.instance_ids)):
            share = engine.execute(shares_table.select().where(
                instance['share_id'] == shares_table.c.id)).first()
            self.test_case.assertEqual(
                next((x for x in self.some_shares if share['id'] == x['id']),
                     None)['share_type_id'],
                instance['share_type_id'])

        for share in engine.execute(share_instances_table.select().where(
                shares_table.c.id in self.share_ids)):
            self.test_case.assertNotIn('share_type_id', share)

    def check_downgrade(self, engine):

        shares_table = utils.load_table('shares', engine)
        share_instances_table = utils.load_table('share_instances', engine)

        for instance in engine.execute(share_instances_table.select().where(
                share_instances_table.c.id in self.instance_ids)):
            self.test_case.assertNotIn('share_type_id', instance)

        for share in engine.execute(share_instances_table.select().where(
                shares_table.c.id in self.share_ids)):
            self.test_case.assertEqual(
                next((x for x in self.some_shares if share['id'] == x['id']),
                     None)['share_type_id'],
                share['share_type_id'])
