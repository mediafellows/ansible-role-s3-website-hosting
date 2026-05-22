#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright (c) 2017 Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = r"""
---

version_added: 12.0.0
module: cloudfront_origin_access_control

short_description: Create, update and delete origin access identities for a
                   CloudFront distribution

description:
  - Allows for easy creation, updating and deletion of origin access controls to be used with Cloudfront origins.

author:
  - Stefan Horning (@stefanhorning)

options:
    state:
      description: If the named resource should exist.
      choices:
        - present
        - absent
      default: present
      type: str
    name:
      description:
        - Name of the origin access control
      required: true
      type: str
    description:
      description:
        - A description to describe the CloudFront origin access control.
      required: false
      type: str
   service:
      description:
        - The AWS service used with this access control config that Cloudront connects to
      required: true
       choices:
        - s3
        - mediastore
        - mediapackagev2
        - lambda
      default: s3
      type: str

notes:
  - Does not support check mode.

extends_documentation_fragment:
  - amazon.aws.common.modules
  - amazon.aws.region.modules
  - amazon.aws.boto3
"""

EXAMPLES = r"""

- name: create an origin access control
  community.aws.cloudfront_origin_access_control:
    name: my-access-control-for-s3
    service: s3
    description: A Cloudfront access control config to be used with s3 origins
    state: present

- name: update an existing origin access control using caller_reference as an identifier
  community.aws.cloudfront_origin_access_control:
    origin_access_control_id: E17DRN9XUOAHZX
    caller_reference: this is an example reference
    comment: this is a new comment

- name: delete an existing origin access control using caller_reference as an identifier
  community.aws.cloudfront_origin_access_control:
    state: absent
    caller_reference: this is an example reference
    comment: this is a new comment
"""

RETURN = r"""
origin_access_control:
  description: The origin access control's information.
  returned: always
  type: complex
  contains:
    service:
      description: the AWS service specified
      returned: always
      type: str
    id:
      description: a unique identifier of the oac
      returned: always
      type: str
    description:
      description: the descritpion of th oac
      returned: always
      type: str
    signing_protocol:
      description: the signing protocol used (only sigv4 for now)
      returned: always
      type: str
    signing_behavior:
      description: the signing behaviour used
      returned: always
      type: str      
e_tag:
  description: The current version of the origin access control created.
  returned: always
  type: str
location:
  description: The fully qualified URI of the new origin access control just created.
  returned: when initially created
  type: str
"""

import datetime

try:
    from botocore.exceptions import BotoCoreError
    from botocore.exceptions import ClientError
except ImportError:
    pass  # caught by imported AnsibleAWSModule

from ansible.module_utils.common.dict_transformations import camel_dict_to_snake_dict

from ansible_collections.amazon.aws.plugins.module_utils.botocore import is_boto3_error_code
from ansible_collections.amazon.aws.plugins.module_utils.cloudfront_facts import CloudFrontFactsServiceManager

from ansible_collections.community.aws.plugins.module_utils.modules import AnsibleCommunityAWSModule as AnsibleAWSModule


class CloudFrontOriginAccesscontrolServiceManager(object):
    """
    Handles CloudFront origin access control service calls to aws
    """

    def __init__(self, module):
        self.module = module
        self.client = module.client("cloudfront")

    def create_origin_access_control(self, name, description, service):
        try:
            return self.client.create_origin_access_control(
                OriginAccessControlConfig={
                    "Name": name,
                    "Description": description,
                    "SigningProtocol": "sigv4",
                    "SigningBehavior": "always",
                    "OriginAccessControlOriginType": service
                }
            )
        except (ClientError, BotoCoreError) as e:
            self.module.fail_json_aws(e, msg="Error creating cloud front origin access control.")

    def delete_origin_access_control(self, origin_access_control_id, e_tag):
        try:
            result = self.client.delete_origin_access_control(Id=origin_access_control_id, IfMatch=e_tag)
            return result, True
        except (ClientError, BotoCoreError) as e:
            self.module.fail_json_aws(e, msg="Error deleting Origin Access Control.")

    def update_origin_access_control(self, caller_reference, comment, origin_access_control_id, e_tag):
        changed = False
        new_config = {"CallerReference": caller_reference, "Comment": comment}

        try:
            current_config = self.client.get_origin_access_control_config(Id=origin_access_control_id)[
                "OriginAccessControlConfig"
            ]
        except (ClientError, BotoCoreError) as e:
            self.module.fail_json_aws(e, msg="Error getting Origin Access Control config.")

        if new_config != current_config:
            changed = True

        try:
            # If the CallerReference is a value already sent in a previous control request
            # the returned value is that of the original request
            result = self.client.update_origin_access_control(
                CloudFrontOriginAccessControlConfig=new_config,
                Id=origin_access_control_id,
                IfMatch=e_tag,
            )
        except (ClientError, BotoCoreError) as e:
            self.module.fail_json_aws(e, msg="Error updating Origin Access Control.")

        return result, changed


class CloudFrontOriginAccessControlValidationManager(object):
    """
    Manages CloudFront Origin Access Identities
    """

    def __init__(self, module):
        self.module = module
        self.__cloudfront_facts_mgr = CloudFrontFactsServiceManager(module)

    def describe_origin_access_control(self, origin_access_control_id, fail_if_missing=True):
        try:
            return self.__cloudfront_facts_mgr.get_origin_access_control(
                id=origin_access_control_id, fail_if_error=False
            )
        except is_boto3_error_code("NoSuchCloudFrontOriginAccessControl") as e:  # pylint: disable=duplicate-except
            if fail_if_missing:
                self.module.fail_json_aws(e, msg="Error getting etag from origin_access_control.")
            return {}
        except (ClientError, BotoCoreError) as e:  # pylint: disable=duplicate-except
            self.module.fail_json_aws(e, msg="Error getting etag from origin_access_control.")

    def validate_etag_from_origin_access_control_id(self, origin_access_control_id, fail_if_missing):
        oac = self.describe_origin_access_control(origin_access_control_id, fail_if_missing)
        if oac is not None:
            return oac.get("ETag")

    def validate_origin_access_control_id_from_caller_reference(self, caller_reference):
        origin_access_identities = self.__cloudfront_facts_mgr.list_origin_access_identities()
        origin_origin_access_control_ids = [oac.get("Id") for oac in origin_access_identities]
        for origin_access_control_id in origin_origin_access_control_ids:
            oac_config = self.__cloudfront_facts_mgr.get_origin_access_control_config(id=origin_access_control_id)
            temp_caller_reference = oac_config.get("CloudFrontOriginAccessControlConfig").get("CallerReference")
            if temp_caller_reference == caller_reference:
                return origin_access_control_id

    def validate_comment(self, comment):
        if comment is None:
            return "origin access control created by Ansible with datetime " + datetime.datetime.now().strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            )
        return comment

    def validate_caller_reference_from_origin_access_control_id(self, origin_access_control_id, caller_reference):
        if caller_reference is None:
            if origin_access_control_id is None:
                return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")
            oac = self.describe_origin_access_control(origin_access_control_id, fail_if_missing=True)
            origin_access_config = oac.get("CloudFrontOriginAccessControl", {}).get(
                "CloudFrontOriginAccessControlConfig", {}
            )
            return origin_access_config.get("CallerReference")
        return caller_reference


def main():
    argument_spec = dict(
        state=dict(choices=["present", "absent"], default="present"),
        name=dict(required=True),
        description=dict()
        service=dict(choices=["s3", "mediastore", "mediapackagev2", "lambda"], default="s3")
    )

    result = {}
    e_tag = None
    changed = False

    module = AnsibleAWSModule(argument_spec=argument_spec, supports_check_mode=False)
    service_mgr = CloudFrontOriginAccessControlServiceManager(module)
    validation_mgr = CloudFrontOriginAccessControlValidationManager(module)

    state = module.params.get("state")
    caller_reference = module.params.get("caller_reference")

    comment = module.params.get("comment")
    origin_access_control_id = module.params.get("origin_access_control_id")

    if origin_access_control_id is None and caller_reference is not None:
        origin_access_control_id = validation_mgr.validate_origin_access_control_id_from_caller_reference(
            caller_reference
        )

    if state == "present":
        comment = validation_mgr.validate_comment(comment)
        caller_reference = validation_mgr.validate_caller_reference_from_origin_access_control_id(
            origin_access_control_id, caller_reference
        )
        if origin_access_control_id is not None:
            e_tag = validation_mgr.validate_etag_from_origin_access_control_id(origin_access_control_id, True)
            # update cloudfront origin access control
            result, changed = service_mgr.update_origin_access_control(
                caller_reference, comment, origin_access_control_id, e_tag
            )
        else:
            # create cloudfront origin access control
            result = service_mgr.create_origin_access_control(name, description, service)
            changed = True
    else:
        e_tag = validation_mgr.validate_etag_from_origin_access_control_id(origin_access_control_id, False)
        if e_tag:
            result, changed = service_mgr.delete_origin_access_control(origin_access_control_id, e_tag)

    result.pop("ResponseMetadata", None)

    module.exit_json(changed=changed, **camel_dict_to_snake_dict(result))


if __name__ == "__main__":
    main()
