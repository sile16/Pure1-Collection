# Pure Storage Matthew Robertson 2020
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from ansible.errors import AnsibleError
from ansible.plugins.inventory import BaseInventoryPlugin, Constructable
from pathlib import Path
from pypureclient import pure1

DOCUMENTATION = '''
    name: purestorage.pure1.pure1_inventory
    plugin_type: inventory
    short_description: Pure Storage Pure1 inventory source
    requirements:
        - py-pure-client
    extends_documentation_fragment:
        - constructed
    description:
        - Get inventory arrays from Pure Storage Pure1
        - Uses a YAML configuration file that ends with pure1.(yml|yaml) .
    options:
        plugin:
            description: token that ensures this is a source file for the 'pure1' plugin.
            required: True
            choices: ['purestorage.pure1.pure1_inventory']
        app_id:
          description: The Pure1 api key id, created in the Pure1 dashboard under Administrator->API Registration
          required: True
          env:
              - name: PURE1_APP_ID
        private_key_file:
          description: The path of the private key to use
          required: True
          env:
              - name: PURE1_PRIVATE_KEY_FILE
        
        private_key_password:
          description: The password of the private key, if encrypted
          env:
            - name: PURE1_PRIVATE_KEY_PASSWORD
        array_filter:
          description:
            - A Pure1 filter string, using when querying arrays. Can only filter or data returned on Get arrays endpoint.
            - The array_filter and tag_filter will be combined to only return arrays that fit both.
            - see U(https://blog.purestorage.com/pure1-rest-api-part-3/)
        tag_filter:
          description:
            - Additional filter when requesting tags, only filters on data returned on Get arrays/tags endpoint.
            - The arrays_filter and tag filter will be combined to only return arrays that fit both.
            - "format of {'tag_name': 'Department', 'value: 'Finance'} "
          type: dict
'''

EXAMPLES = '''
# Minimal example 1 using environment vars or instance role credentials
# Fetch all arrays visible to this api key.
# Use: U(https://blog.purestorage.com/introducing-the-pure1-rest-api/) for guidance
# to create the private/public key and register on pure1 to get the Pure1 App id
plugin: purestorage.pure1.pure1_inventory
app_id: pure1:apikey:dfjadsljADF2s 
private_key_file: ~/mykeys/pure1_test_private_key.pem

# Example 2 using filters, ignoring permission errors, and specifying the hostname precedence
plugin: purestorage.pure1.pure1_inventory
app_id: pure1:apikey:dfjadsljADF2s 
private_key_file: ~/mykeys/pure1_test_private_key.pem
array_filter: contains(name, 'sn1-405')
tag_filter:
  tag_name: Department
  value: Finance

# Example 3 using constructed features to create groups
plugin: purestorage.pure1.pure1_inventory
app_id: pure1:apikey:dfjadsljADF2s 
private_key_file: ~/mykeys/pure1_test_private_key.pem
# keyed_groups may be used to create custom groups
keyed_groups:
  - prefix: pure_mod
    key: pure_model
  - prefix: tag
    key: tags
'''


class InventoryModule(BaseInventoryPlugin, Constructable):

    NAME = 'purestorage.pure1.pure1_inventory'  # used internally by Ansible, it should match the file name but not required

    def verify_file(self, path):
        ''' return true/false if this is possibly a valid file for this plugin to consume '''
        valid = False
        if super(InventoryModule, self).verify_file(path):
            # base class verifies that file exists and is readable by current user
            if path.endswith(('pure1.yaml', 'pure1.yml')):
                valid = True
        return valid

    def display_response_error(self, response):
        # Do you have internet access ?
        msg = " Error getting results. Check internet access."
        msg += str(response.errors[0].message)
        if response.errors[0].context is not None:
            msg += str(response.errors[0].context)
        raise AnsibleError(msg)

    def get_arrays(self, pure1Client):
        # Get all  Arrays, FlashArray & FlashBlade.
        array_filter_string=None

        tag_filter = self.get_option('tag_filter')
        array_filter = self.get_option('array_filter')

        if array_filter and not array_filter == "":
            array_filter_string = array_filter

        if tag_filter and 'tag_name' in tag_filter and 'value' in tag_filter:
            if array_filter_string:
                array_filter_string += ' and '
            else:
                array_filter_string = ""
            array_filter_string += "tags('{}','{}')".format(tag_filter['tag_name'], tag_filter['value'])

        if array_filter_string:
            response = pure1Client.get_arrays(filter=array_filter_string)
        else:
            response = pure1Client.get_arrays()


        # Check to make sure we successfully connected, 200=OK
        if response.status_code != 200:
            self.display_response_error(response)

        # this gets all the response items which is a
        # generator which has no length, by pulling all into a
        # list it has a length.
        arrays = list(response.items)
        return arrays

    def get_tags(self, pure1Client):
        # Get all tags, FlashArray & FlashBlade.
        response = pure1Client.get_arrays_tags()

        # Check to make sure we successfully connected, 200=OK
        if response.status_code != 200:
            self.display_response_error(response)

        # this gets all the response items which is a
        # generator which has no length, by pulling all into a
        # list it has a length.
        arrays_tags = list(response.items)

        # put all the tags into a dictionary organized by array
        tags_byarray = {}
        for tag in arrays_tags:
            if tag.resource.name not in tags_byarray:
                tags_byarray[tag.resource.name] = {}
            tags_byarray[tag.resource.name][tag.key] = tag.value
        return tags_byarray

    def get_nets(self, pure1Client):
        # Get all tags, FlashArray & FlashBlade.
        query_filter = "contains(name, 'vir')"
        response = pure1Client.get_network_interfaces(filter=query_filter)

        # Check to make sure we successfully connected, 200=OK
        if response.status_code != 200:
            self.display_response_error(response)

        # this gets all the response items which is a
        # generator which has no length, by pulling all into a
        # list it has a length.
        arrays_nets = list(response.items)

        # put all the tags into a dictionary organized by array
        nets_byarray = {}
        for net in arrays_nets:
            if 'vir' in net.name and net.address:
                array = net.arrays[0].name
                ip = net.address
                nets_byarray[array] = {}
                nets_byarray[array]['ip'] = ip
        return nets_byarray

    def generate_fleet_inventory(self, pure1Client):

        arrays = self.get_arrays(pure1Client)
        tags = self.get_tags(pure1Client)
        nets = self.get_nets(pure1Client)

        # create two main groups
        self.inventory.add_group('pure_flasharray')
        self.inventory.add_group('pure_flashblade')

        # Use constructed if applicable
        strict = self.get_option('strict')

        for array in arrays:
            array_vars = {}

            if 'FA' in array.os:
                # FA Specific values
                group = 'pure_flasharray'
                array_vars['tags'] = tags.get(array.name, {})
                if array.name in nets and 'ip' in nets[array.name]:
                    array_vars['fa_url'] = nets[array.name]['ip']

            elif 'FB' in array.os:
                # FB specific values
                group = 'pure_flashblade'
                # get the tags, otherwise return default empty dict
                array_vars['tags'] = tags.get(array.name, {})
                if array.name in nets and 'ip' in nets[array.name]:
                    array_vars['fb_url'] = nets[array.name]['ip']

            # assign some common vars.
            array_vars['pure_model'] = array.model
            array_vars['pure_version'] = array.version

            # assign some other vars.
            self.inventory.add_host(array.name, group=group)
            for k in array_vars:
                self.inventory.set_variable(array.name, k, array_vars[k])

            # Create groups based on variable values and add the corresponding hosts to it
            self._add_host_to_keyed_groups(self.get_option('keyed_groups'), array_vars, array.name, strict=strict)

    def parse(self, inventory, loader, path, cache=True):
        # call base method to ensure properties are available for use with other helper methods
        super(InventoryModule, self).parse(inventory, loader, path, cache)

        # this method will parse 'common format' inventory sources and
        # update any options declared in DOCUMENTATION as needed
        self._read_config_data(path)

        app_id = self.get_option('app_id')
        private_key_file = Path(self.get_option('private_key_file')).expanduser()
        private_key_password = self.get_option('private_key_password')

        pure1Client = pure1.Client(app_id=app_id,
                                   private_key_file=private_key_file,
                                   private_key_password=private_key_password
                                   )

        self.generate_fleet_inventory(pure1Client)
