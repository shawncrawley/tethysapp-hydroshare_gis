from django.core.files.uploadedfile import TemporaryUploadedFile
from hs_restclient import HydroShare, HydroShareAuthOAuth2
from django.http import JsonResponse
from django.conf import settings
from tethys_sdk.services import get_spatial_dataset_engine

import requests
import zipfile
import os
import sqlite3

hs_hostname = 'www.hydroshare.org'
geoserver_name = 'localhost_geoserver'
geoserver_url = 'http://127.0.0.1:8181/geoserver'
workspace_id = 'hydroshare_gis'
uri = 'http://127.0.0.1:8000/apps/hydroshare-gis'


def get_oauth_hs(request):
    global hs_hostname

    client_id = getattr(settings, 'SOCIAL_AUTH_HYDROSHARE_KEY', 'None')
    client_secret = getattr(settings, 'SOCIAL_AUTH_HYDROSHARE_SECRET', 'None')

    # Throws django.core.exceptions.ObjectDoesNotExist if current user is not signed in via HydroShare OAuth
    token = request.user.social_auth.get(provider='hydroshare').extra_data['token_dict']
    auth = HydroShareAuthOAuth2(client_id, client_secret, token=token)

    return HydroShare(auth=auth, hostname=hs_hostname)


def get_json_response(response_type, message):
    return JsonResponse({response_type: message})


def upload_file_to_geoserver(res_id, res_type, res_file, is_zip):
    global geoserver_name, workspace_id, uri
    result = None

    engine = return_spatial_dataset_engine()

    store_id = 'res_%s' % res_id
    full_store_id = '%s:%s' % (workspace_id, store_id)

    if res_type == 'RasterResource':
        result = engine.create_coverage_resource(store_id=full_store_id,
                                                 coverage_file=res_file,
                                                 coverage_type='geotiff',
                                                 overwrite=True)

    elif res_type == 'GeographicFeatureResource':
        if is_zip is True:
            result = engine.create_shapefile_resource(store_id=full_store_id,
                                                      shapefile_zip=res_file,
                                                      overwrite=True)
        elif type(res_file) is not unicode:
            result = engine.create_shapefile_resource(store_id=full_store_id,
                                                      shapefile_upload=res_file,
                                                      overwrite=True)
        else:
            result = engine.create_shapefile_resource(store_id=full_store_id,
                                                      shapefile_base=str(res_file),
                                                      overwrite=True)

    # Check if it was successful
    if result:
        if not result['success']:
            raise Exception()
        else:
            layer_name = engine.list_resources(store=store_id)['result'][0]
            layer_id = '%s:%s' % (workspace_id, layer_name)
            return layer_name, layer_id


def make_file_zipfile(res_file, filename, zip_path):
    if not os.path.exists(zip_path):
        if not os.path.exists(os.path.dirname(zip_path)):
            os.mkdir(os.path.dirname(zip_path))

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, False) as zip_object:
        if type(res_file) is not TemporaryUploadedFile:
            zip_object.write(res_file)
        else:
            zip_object.writestr(filename, res_file.read())
        zip_object.close()


def return_spatial_dataset_engine():
    global geoserver_name, workspace_id, uri

    engine = get_spatial_dataset_engine(name=geoserver_name)
    if not engine.get_workspace(workspace_id)['success']:
        # Workspace does not exist and must be created
        engine.create_workspace(workspace_id=workspace_id, uri=uri)
    return engine


def get_layer_extents_and_attributes(res_id, layer_name, res_type):
    global geoserver_url

    if res_type == 'GeographicFeatureResource':
        url = geoserver_url + '/rest/workspaces/hydroshare_gis/datastores/res_' + res_id + \
              '/featuretypes/' + layer_name + '.json'
    else:
        url = geoserver_url + '/rest/workspaces/hydroshare_gis/coveragestores/res_' + res_id + \
              '/coverages/' + layer_name + '.json'

    username = 'admin'
    password = 'geoserver'
    r = requests.get(url, auth=(username, password))
    json = r.json()

    if res_type == 'GeographicFeatureResource':
        extents = json['featureType']['latLonBoundingBox']

        attributes = json['featureType']['attributes']['attribute']
        attributes_string = ''
        for attribute in attributes:
            if attribute['name'] != 'the_geom':
                attributes_string += attribute['name'] + ','
    else:
        extents = json['coverage']['latLonBoundingBox']
        attributes_string = ','

    return extents, attributes_string[:-1]


def get_geoserver_url():
    global geoserver_url
    return geoserver_url


def extract_site_info_from_time_series(sqlite_file_path):
    site_info = None
    with sqlite3.connect(sqlite_file_path) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute('SELECT * FROM Sites')
        site = cur.fetchone()
        if site:
            if site['Latitude'] and site['Longitude']:
                site_info = {'lon': site['Longitude'], 'lat': site['Latitude'], 'units': 'Decimal degrees'}
                if site['SpatialReferenceID']:
                    cur.execute('SELECT * FROM SpatialReferences WHERE SpatialReferenceID=?',
                                (site['SpatialReferenceID'],))
                    spatialref = cur.fetchone()
                    if spatialref:
                        if spatialref['SRSName']:
                            site_info['projection'] = spatialref['SRSName']

    return site_info


def format_file_size(size):
    units_key = 0
    while size > 999:
        size /= 1000.0
        units_key += 1

    units_dict = {
        0: 'bytes',
        1: 'kB',
        2: 'MB',
        3: 'GB',
        4: 'TB',
        5: 'PB'
    }
    print '{:3.1f}'.format(size) + units_dict[units_key]
    return '{:3.1f}'.format(size) + units_dict[units_key]
