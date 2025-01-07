import redis
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

mac_address = '00:11:22:33:44:55'
# Example data for the local database
local_example_data = {
    'mac': mac_address,
    'protocols': 'TCP',
    'ip': '192.168.1.1',
    'id': 'device123',
    'name': 'LocalDevice',
    'vendor': 'LocalVendor',
    'hw': 'HW1',
    'sw': 'SW1',
    'productID': 'ProductLocal',
    'serial': 'SerialLocal',
    'device_type': 'Router',
    'id_weight': '1',
    'name_weight': '1',
    'vendor_weight': '1',
    'hw_weight': '1',
    'sw_weight': '1',
    'productID_weight': '1',
    'serial_weight': '1',
    'device_type_weight': '1',
    'timestamp': '2023-10-05T14:48:00',
    'up_to_date': 'True'
}
# Example data for the remote database
remote_example_data = {
    'mac': mac_address,
    'protocols': 'TCP',
    'ip': '192.168.1.2',
    'id': 'device123',
    'name': 'RemoteDevice',
    'vendor': 'RemoteVendor',
    'hw': 'HW1',
    'sw': 'SW2',
    'productID': 'ProductRemote',
    'serial': 'SerialRemote',
    'device_type': 'Router',
    'id_weight': '1',
    'name_weight': '1',
    'vendor_weight': '1',
    'hw_weight': '1',
    'sw_weight': '1',
    'productID_weight': '1',
    'serial_weight': '1',
    'device_type_weight': '1',
    'timestamp': '2023-10-05T14:49:00',
    'up_to_date': 'False'
}

class eps:
    def __init__(self,):
        start_time = time.time()
        logger.warning(f'redis DB creation - Start')
        # Use db=0 for local data
        self.local_db = redis.Redis(host='localhost', port=6379, db=0)
        # Use db=1 for remote data
        self.remote_db = redis.Redis(host='localhost', port=6379, db=1)

        self.local_db.flushdb()
        self.remote_db.flushdb()
        # print(f'local entries: {local_db.dbsize()}, remote entries: {remote_db.dbsize()}')
        self.local_db.hset(f"endpoint:{mac_address}", mapping=local_example_data)
        self.remote_db.hset(f"endpoint:{mac_address}", mapping=remote_example_data)
        # print(f'after template, local entries: {local_db.dbsize()}, remote entries: {remote_db.dbsize()}')
        end_time = time.time()
        logger.warning(f'redis DB creation - Completed: {round(end_time - start_time,4)}sec')

    ## Compare the values provided against either the local or remote cache redis DB
    def add_or_update_entry(self, redis_db, data_array, ise_sync=False):
        # Map array values to field names
        fields = [
            'mac', 'protocols', 'ip', 'id', 'name', 'vendor', 'hw', 'sw', 
            'productID', 'serial', 'device_type', 'id_weight', 'name_weight', 
            'vendor_weight', 'hw_weight', 'sw_weight', 'productID_weight', 
            'serial_weight', 'device_type_weight'
        ]
        # Identify Redis database (local or remote)
        redis_id = redis_db.connection_pool.connection_kwargs.get('db', 0)
        if redis_id == 0:       ## If referring to the parser's local redis db
            new_entry = {fields[i]: str(data_array[i]) for i in range(len(fields))}
        elif redis_id == 1:     ## If utilizing the remote cache db
            new_entry = {field: str(data_array.get(field, '')) for field in fields}

        # ## If this upadte includes current data from ISE
        # if ise_sync == True:
        #     new_entry['synced_to_ise'] = 'True'

        # Add dynamically generated timestamp
        new_entry['timestamp'] = datetime.now().isoformat()
        mac = new_entry['mac']
        existing_data = redis_db.hgetall(f"endpoint:{mac}")

        # Convert existing data from bytes to string if it exists
        if existing_data:
            existing_data = {k.decode('utf-8'): v.decode('utf-8') for k, v in existing_data.items()}
            
            # Check weight fields to decide whether to update
            weight_fields = ['id_weight', 'name_weight', 'vendor_weight', 'hw_weight', 'sw_weight', 
                            'productID_weight', 'serial_weight', 'device_type_weight']
            updated = False
            
            for field in weight_fields:
                new_weight = int(new_entry[field])
                exist_weight = int(existing_data.get(field, 0))
                corresponding_field = field.replace('_weight', '')

                if new_weight > exist_weight:
                    # Update both the weight and the corresponding field value
                    existing_data[field] = new_entry[field]
                    existing_data[corresponding_field] = new_entry[corresponding_field]
                    updated = True
            ## If existing data does not have same protocol list, check for individual protocols and append any new entries
            if new_entry['protocols'] != existing_data['protocols']:
                new_protos = set(new_entry['protocols'].split(','))
                existing_protos = set(existing_data['protocols'].split(','))
                for proto in new_protos:
                    if proto not in existing_protos:
                        existing_data['protocols'] = existing_data['protocols'] + ',' + proto
                        updated = True

            if updated:
                # Update the 'synced_to_ise' field if we're updating the record
                existing_data['synced_to_ise'] = 'False'
                logger.debug(f'Record for MAC {mac} updated.')
            else:
                # Update only the timestamp if weights are not higher to show data is still valid as of new time
                existing_data['timestamp'] = new_entry['timestamp']
                logger.debug(f"Record for MAC {mac} not updated; weights not higher.")
                return
        else:
            # If no existing data, create a new entry
            existing_data = new_entry
            existing_data['synced_to_ise'] = 'False'
            logger.debug(f'Record for MAC {mac} added to database')

        # Add or update the record in the local database
        redis_db.hset(f"endpoint:{mac}", mapping=existing_data)
        # Add a lifetime to the mac address record for when it should be purged due to inactivity (10min interval)
        redis_db.expire(f"endpoint:{mac}",600)
        redis_db.sadd("endpoints:macs", mac)
        # logger.debug(f"Record for MAC {mac} added or updated.")

    ## Compare the values provided against the remote cache DB and return TRUE or FALSE for entry presence
    def check_remote_cache(self, redis_db, mac_address, values):
        existing_values = redis_db.hgetall(f"endpoint:{mac_address}")
        
        # Define the fields to check
        fields = [
            'mac', 'protocols', 'ip', 'id', 'name', 'vendor', 'hw', 'sw', 
            'productID', 'serial', 'device_type', 'id_weight', 'name_weight', 
            'vendor_weight', 'hw_weight', 'sw_weight', 'productID_weight', 
            'serial_weight', 'device_type_weight'
        ]

        # Check if MAC address exists in the database
        if existing_values:
            # Decode the existing values from bytes to strings
            existing_values_decoded = {k.decode('utf-8'): v.decode('utf-8') for k, v in existing_values.items()}

            # Filter existing values to only include the specified fields
            existing_filtered = {field: existing_values_decoded.get(field, '') for field in fields}

            certainties = values.get('isepyCertainty', '').split(',')

            # Create new_filtered by mapping values from 'values' dictionary to 'fields'
            new_filtered = {
                'mac':mac_address,
                'protocols': values.get('isepyProtocols', ''),
                'ip': values.get('isepyIP', ''),
                'id':'',
                'name': (values.get('isepyHostname', "")).replace("'","’"),
                'vendor': values.get('isepyVendor', ''),
                'hw': values.get('isepyModel', ''),
                'sw': values.get('isepyOS', ''),
                'productID': values.get('isepyDeviceID', ''),
                'serial': values.get('isepySerial', ''),
                'device_type': values.get('isepyType', ''),
                'id_weight':'0',
                'name_weight':certainties[0],
                'vendor_weight':certainties[1],
                'hw_weight':certainties[2],
                'sw_weight':certainties[3],
                'productID_weight':certainties[4],
                'serial_weight':certainties[5],
                'device_type_weight':certainties[6]
            }

            # Compare the filtered existing values with new values
            if existing_filtered != new_filtered:
                logger.debug(f"redis remote cache MAC address {mac_address} exists and has different values")
                # logger.debug(f'{mac_address} existing: {existing_filtered} - new values: {new_filtered}')
                return False
            else:
                logger.debug(f"redis remote cache MAC address {mac_address} exists and already has the same values")
                
                return True
        else:
            logger.debug(f"no entry exists in redis remote cache for MAC address {mac_address}")
            return False

    ## Compare the values provided against the remote cache DB and return TRUE or FALSE for entry presence
    async def check_remote_cache_async(self, redis_db, mac_address, values):
        existing_values = redis_db.hgetall(f"endpoint:{mac_address}")
        
        # Define the fields to check
        fields = [
            'mac', 'protocols', 'ip', 'id', 'name', 'vendor', 'hw', 'sw', 
            'productID', 'serial', 'device_type', 'id_weight', 'name_weight', 
            'vendor_weight', 'hw_weight', 'sw_weight', 'productID_weight', 
            'serial_weight', 'device_type_weight'
        ]

        # Check if MAC address exists in the database
        if existing_values:
            # Decode the existing values from bytes to strings
            existing_values_decoded = {k.decode('utf-8'): v.decode('utf-8') for k, v in existing_values.items()}

            # Filter existing values to only include the specified fields
            existing_filtered = {field: existing_values_decoded.get(field, '') for field in fields}

            certainties = values.get('isepyCertainty', '').split(',')

            # Create new_filtered by mapping values from 'values' dictionary to 'fields'
            new_filtered = {
                'mac':mac_address,
                'protocols': values.get('isepyProtocols', ''),
                'ip': values.get('isepyIP', ''),
                'id':'',
                'name': (values.get('isepyHostname', "")).replace("'","’"),
                'vendor': values.get('isepyVendor', ''),
                'hw': values.get('isepyModel', ''),
                'sw': values.get('isepyOS', ''),
                'productID': values.get('isepyDeviceID', ''),
                'serial': values.get('isepySerial', ''),
                'device_type': values.get('isepyType', ''),
                'id_weight':'0',
                'name_weight':certainties[0],
                'vendor_weight':certainties[1],
                'hw_weight':certainties[2],
                'sw_weight':certainties[3],
                'productID_weight':certainties[4],
                'serial_weight':certainties[5],
                'device_type_weight':certainties[6]
            }

            # Compare the filtered existing values with new values
            if existing_filtered != new_filtered:
                logger.debug(f"redis remote cache MAC address {mac_address} exists and has different values")
                # logger.debug(f'{mac_address} existing: {existing_filtered} - new values: {new_filtered}')
                return False
            else:
                logger.debug(f"redis remote cache MAC address {mac_address} exists and already has the same values")
                return True
        else:
            logger.debug(f"no entry exists in redis remote cache for MAC address {mac_address}")
            return False

    ## Retrieve all MAC addresses stored in the local database
    def updated_local_entries(self, local_redis):
        mac_addresses = local_redis.smembers("endpoints:macs")
        updated_records = []

        for mac in mac_addresses:
            # Decode MAC address from bytes to string
            mac_str = mac.decode('utf-8')
            
            # Retrieve the hash for each MAC address
            entry = local_redis.hgetall(f"endpoint:{mac_str}")
            entry = {k.decode('utf-8'): v.decode('utf-8') for k, v in entry.items()}

            # Check if the 'synced_to_ise' field is set to 'False'
            if entry.get('synced_to_ise') == 'False':
                updated_records.append(entry)

        return updated_records

    ## Retrieve all MAC addresses stored in the local database
    async def updated_local_entries_async(self, local_redis):
        mac_addresses = local_redis.smembers("endpoints:macs")
        updated_records = []

        for mac in mac_addresses:
            # Decode MAC address from bytes to string
            mac_str = mac.decode('utf-8')
            
            # Retrieve the hash for each MAC address
            entry = local_redis.hgetall(f"endpoint:{mac_str}")
            entry = {k.decode('utf-8'): v.decode('utf-8') for k, v in entry.items()}

            # Check if the 'updated' field is set to 'True'
            if entry.get('synced_to_ise') == 'False':
                updated_records.append(entry)

        return updated_records

    # Print all entries of defined redis DB
    def print_endpoints(self,redis_db):
        # Define the key pattern or specific keys you want to fetch
        key_pattern = '*:*'  # Adjust this pattern based on your data

        # Retrieve keys matching the pattern
        keys = redis_db.keys(key_pattern)

        # Define the column names
        column_names = [
            'mac', 'protocols', 'ip', 'id', 'name', 'vendor', 'hw', 'sw',
            'productID', 'serial', 'device_type', 'id_weight', 'name_weight',
            'vendor_weight', 'hw_weight', 'sw_weight', 'productID_weight',
            'serial_weight', 'device_type_weight', 'timestamp', 'synced_to_ise'
        ]

        # Print the column names
        print('|'.join(column_names))

        # Iterate through each key and fetch its data
        i = 0
        while i < len(keys) - 1:
            key = keys[i]

            try:
                # Check if the key is of type 'hash'
                if redis_db.type(key).decode('utf-8') == 'hash':
                    entry = redis_db.hgetall(key)
                    row = [entry.get(col.encode(), b'').decode() for col in column_names]
                    print('|'.join(row))
                else:
                    print(f"Skipping key {key.decode('utf-8')} - not a hash type.")
            except redis.exceptions.ResponseError as e:
                print(f"Error processing key {key.decode('utf-8')}: {e}")
            i += 1