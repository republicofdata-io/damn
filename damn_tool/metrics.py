import boto3
import click
import datetime
import json
import pyperclip

from .utils.helpers import (
    init_connectors,
    package_command_output, 
    print_packaged_command_output, 
    run_and_capture
)


def get_orchestrator_data(orchestrator_connector, asset):
    asset_list = asset.split('/')

    query = f"""
    query AssetMetricsByKey {{
        assetOrError(assetKey: {{path: {json.dumps(asset_list)}}}) {{
            __typename
            ... on Asset {{
                id
                assetMaterializations(limit: 1){{
                    runId
                    timestamp
                    stepStats{{
                        stepKey
                        status
                        startTime
                        endTime
                    }}
                }}
                definition{{
                    freshnessInfo{{
                        currentMinutesLate
                    }}
                    partitionStats{{
                        numPartitions
                        numMaterialized
                        numFailed
                    }}
                }}
            }}
            ... on AssetNotFoundError {{
                message
            }}
        }}
    }}
    """

    result = orchestrator_connector.execute(query)

    run_id = 'N/A'
    status = 'N/A'
    start_time = 'N/A'
    end_time = 'N/A'
    elapsed_time = 'N/A'
    num_partitions = 'N/A'
    num_materialized = 'N/A'
    num_failed = 'N/A'

    asset_info = result["data"]["assetOrError"]

    # Get AssetMaterializations attributes
    if asset_info['assetMaterializations']:
        first_materialization = asset_info['assetMaterializations'][0]
        run_id = first_materialization['runId'] if 'runId' in first_materialization else 'N/A'

        # Extract stepStats if available
        step_stats = first_materialization['stepStats'] if 'stepStats' in first_materialization else {}
        status = step_stats['status'] if 'status' in step_stats else 'N/A'
        
        if 'startTime' in step_stats:
            start_time = datetime.datetime.fromtimestamp(step_stats['startTime']).strftime('%Y-%m-%d %H:%M:%S')

        if 'endTime' in step_stats:
            end_time = datetime.datetime.fromtimestamp(step_stats['endTime']).strftime('%Y-%m-%d %H:%M:%S')

        # Calculate and format elapsed time
        if 'startTime' in step_stats and 'endTime' in step_stats:
            elapsed_seconds = step_stats['endTime'] - step_stats['startTime']
            elapsed_time = str(datetime.timedelta(seconds=elapsed_seconds))
                    
    # Get Definition attributes
    if asset_info['definition']:
        definition = asset_info['definition']
        
        if 'partitionStats' in definition and definition['partitionStats'] is not None:
            partition_stats = definition['partitionStats']
            num_partitions = partition_stats['numPartitions'] if 'numPartitions' in partition_stats else 'N/A'
            num_materialized = partition_stats['numMaterialized'] if 'numMaterialized' in partition_stats else 'N/A'
            num_failed = partition_stats['numFailed'] if 'numFailed' in partition_stats else 'N/A'

    return {
        'run_id': run_id,
        'status': status,
        'start_time': start_time,
        'end_time': end_time,
        'elapsed_time': elapsed_time,
        'num_partitions': num_partitions,
        'num_materialized': num_materialized,
        'num_failed': num_failed
    }


def get_io_manager_data(io_manager_connector, asset):
    # Get S3 items with that asset name
    s3_items = io_manager_connector.list_objects_and_folders(io_manager_connector.config['bucket_name'], io_manager_connector.config['key_prefix'] + "/" + asset)
    
    if s3_items:  # Ensure s3_items is not empty
        return {
            'files': s3_items[0]['num_files'],
            'size': s3_items[0]['file_size'],
            'last_modified': s3_items[0]['last_modified_ts']
        }
    else:
        return {
            'files': 0,
            'size': 0,
            'last_modified': None
        }


def get_data_warehouse_data(data_warehouse_connector, asset):
    sql = """select
        row_count,
        bytes
        
    from information_schema.tables 
    where lower(table_name) = 'movements_dim'
    and lower(table_schema) like '%analytics%'
    """

    result, description = data_warehouse_connector.execute(sql)
    data_warehouse_connector.close()

    if result is not None:
        result_dict = dict(zip([column[0] for column in description], result))
        return {
            'row_count': result_dict.get('ROW_COUNT', None),
            'bytes': result_dict.get('BYTES', None)
        }
    else:
        return {
            'row_count': None,
            'bytes': None
        }


@click.command()
@click.argument('asset', type=str)
@click.option('--orchestrator', default=None, help='Orchestrator service provider to use')
@click.option('--io_manager', default=None, help='IO manager service provider to use')
@click.option('--data-warehouse', default=None, help='Data warehouse service provider to use')
@click.option('--output', default='terminal', help='Destination for command output. Options include `terminal` (default) for standard output, `json` to format output as JSON, or `copy` to copy the output to the clipboard.')
def metrics(asset, orchestrator, io_manager, data_warehouse, output):
    """List your asset's metrics"""
    # Initialize connectors
    orchestrator_connector, io_manager_connector, data_warehouse_connector = init_connectors(orchestrator, io_manager, data_warehouse)
    
    # Get metrics
    orchestrator_data = get_orchestrator_data(orchestrator_connector, asset)
    io_manager_data = get_io_manager_data(io_manager_connector, asset)
    data_warehouse_data = get_data_warehouse_data(data_warehouse_connector, asset)

    data = {
        "Orchestrator Metrics": orchestrator_data,
        "IO Manager Metrics": io_manager_data,
        "Data Warehouse Metrics": data_warehouse_data
    }

    # Package and output metrics
    packaged_command_output = package_command_output('metrics', data)

    if output == 'json':
        print(packaged_command_output)
    elif output == 'copy':
        print_output = run_and_capture(print_packaged_command_output, packaged_command_output)
        markdown_output = print_output.replace('\x1b[36m- ', '- ').replace('\x1b[0m', '')  # Removing the color codes
        pyperclip.copy(markdown_output)
    else:
        print_packaged_command_output(packaged_command_output)