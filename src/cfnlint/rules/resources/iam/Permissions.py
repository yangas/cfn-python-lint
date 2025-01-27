"""
  Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.

  Permission is hereby granted, free of charge, to any person obtaining a copy of this
  software and associated documentation files (the "Software"), to deal in the Software
  without restriction, including without limitation the rights to use, copy, modify,
  merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
  permit persons to whom the Software is furnished to do so.

  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
  INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
  PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
  HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
  OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
  SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""
import json
import six
from cfnlint.helpers import convert_dict
from cfnlint import CloudFormationLintRule
from cfnlint import RuleMatch

import cfnlint.helpers


class Permissions(CloudFormationLintRule):
    """Check IAM Permission configuration"""
    id = 'W3037'
    shortdesc = 'Check IAM Permission configuration'
    description = 'Check for valid IAM Permissions'
    source_url = 'https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements_action.html'
    tags = ['properties', 'iam', 'permissions']
    experimental = True

    IAM_PERMISSION_RESOURCE_TYPES = {
        'AWS::SNS::TopicPolicy': 'PolicyDocument',
        'AWS::S3::BucketPolicy': 'PolicyDocument',
        'AWS::KMS::Key': 'KeyPolicy',
        'AWS::SQS::QueuePolicy': 'PolicyDocument',
        'AWS::Elasticsearch::Domain': 'AccessPolicies',
        'AWS::IAM::Group': 'Policies',
        'AWS::IAM::ManagedPolicy': 'PolicyDocument',
        'AWS::IAM::Policy': 'PolicyDocument',
        'AWS::IAM::Role': 'Policies',
        'AWS::IAM::User': 'Policies',
    }

    def __init__(self):
        """Init"""
        super(Permissions, self).__init__()
        self.service_map = self.load_service_map()
        for resource_type in self.IAM_PERMISSION_RESOURCE_TYPES:
            self.resource_property_types.append(resource_type)

    def load_service_map(self):
        """
        Convert policies.json into a simpler version for more efficient key lookup.
        """
        service_map = cfnlint.helpers.load_resources('data/AdditionalSpecs/Policies.json')['serviceMap']

        policy_service_map = {}

        for _, properties in service_map.items():
            # The services and actions are case insensitive
            service = properties['StringPrefix'].lower()
            actions = [x.lower() for x in properties['Actions']]

            # Some services have the same name for different generations; like elasticloadbalancing.
            if service in policy_service_map:
                policy_service_map[service] += actions
            else:
                policy_service_map[service] = actions

        return policy_service_map

    def check_policy_document(self, value, path, start_mark, end_mark):
        """Check policy document"""
        matches = []

        if isinstance(value, six.string_types):
            try:
                value = convert_dict(json.loads(value), start_mark, end_mark)
            except Exception as ex:  # pylint: disable=W0703,W0612
                message = 'IAM Policy Documents need to be JSON'
                matches.append(RuleMatch(path[:], message))
                return matches

        if not isinstance(value, dict):
            return matches

        for p_vs, p_p in value.items_safe(path[:], (dict)):
            statements = p_vs.get('Statement')
            if statements:
                if isinstance(statements, dict):
                    statements = [statements]
                if isinstance(statements, list):
                    for index, statement in enumerate(statements):
                        actions = []

                        if isinstance(statement, dict):
                            actions.extend(self.get_actions(statement))

                        elif isinstance(statement, list):
                            for effective_permission in statement:
                                actions.extend(self.get_actions(effective_permission))

                        for action in actions:
                            matches.extend(self.check_permissions(action, p_p + ['Statement', index]))

        return matches

    def check_permissions(self, action, path):
        """
        Check if permission is valid
        """
        matches = []
        if action == '*':
            return matches

        service, permission = action.split(':', 1)
        # Get lowercase so we can check case insenstive. Keep the original values for the message
        service_value = service.lower()
        permission_value = permission.lower()

        if service_value in self.service_map:
            if permission_value == '*':
                pass
            elif permission_value.endswith('*'):
                wilcarded_permission = permission_value.split('*')[0]
                if not any(wilcarded_permission in action for action in self.service_map[service_value]):
                    message = 'Invalid permission "{}" for "{}" found in permissions'
                    matches.append(
                        RuleMatch(
                            path,
                            message.format(permission, service)))

            elif permission_value.startswith('*'):
                wilcarded_permission = permission_value.split('*')[1]
                if not any(wilcarded_permission in action for action in self.service_map[service_value]):
                    message = 'Invalid permission "{}" for "{}" found in permissions'
                    matches.append(
                        RuleMatch(
                            path,
                            message.format(permission, service)))
            elif permission_value not in self.service_map[service_value]:
                message = 'Invalid permission "{}" for "{}" found in permissions'
                matches.append(
                    RuleMatch(
                        path,
                        message.format(permission, service)))
        else:
            message = 'Invalid service "{}" found in permissions'
            matches.append(
                RuleMatch(
                    path,
                    message.format(service)))

        return matches

    def get_actions(self, effective_permissions):
        """return all actions from a statement"""

        actions = []

        if 'Action' in effective_permissions:
            if isinstance(effective_permissions.get('Action'), six.string_types):
                actions.append(effective_permissions.get('Action'))
            elif isinstance(effective_permissions.get('Action'), list):
                actions.extend(effective_permissions.get('Action'))

        if 'NotAction' in effective_permissions:
            if isinstance(effective_permissions.get('NotAction'), six.string_types):
                actions.append(effective_permissions.get('NotAction'))
            elif isinstance(effective_permissions.get('Action'), list):
                actions.extend(effective_permissions.get('NotAction'))

        return actions

    def match_resource_properties(self, properties, resourcetype, path, cfn):
        """Check CloudFormation Properties"""
        matches = []

        key = self.IAM_PERMISSION_RESOURCE_TYPES.get(resourcetype)
        for key, value in properties.items():
            if key == 'Policies' and isinstance(value, list):
                for index, policy in enumerate(properties.get(key, [])):
                    matches.extend(
                        cfn.check_value(
                            obj=policy, key='PolicyDocument',
                            path=path[:] + ['Policies', index],
                            check_value=self.check_policy_document,
                            start_mark=key.start_mark, end_mark=key.end_mark,
                        ))
            elif key in ['KeyPolicy', 'PolicyDocument', 'RepositoryPolicyText', 'AccessPolicies']:
                matches.extend(
                    cfn.check_value(
                        obj=properties, key=key,
                        path=path[:],
                        check_value=self.check_policy_document,
                        start_mark=key.start_mark, end_mark=key.end_mark,
                    ))

        return matches
