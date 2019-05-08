#!/usr/bin/env python
# -*- coding: utf-8 -*-

import shutil
import uuid
import time
import json

from flask import render_template, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from flask_cors import CORS
from utils import *

app.config.from_object('config')
CORS(app, resources=r'/*')


@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload():
    # get upload files
    file1 = request.files['file1']
    file2 = request.files['file2']
    # generate client id and create folder
    client_id = str(uuid.uuid1())
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], client_id))
    f_type = []
    for file in [file1, file2]:
        filename = secure_filename(file.filename)
        # convert excel to dataframe
        if filename.endswith('.xlsx') or filename.endswith('xls'):
            dataframe = pd.read_excel(file)
        else:
            dataframe = pd.read_csv(file)
        # handling column name exception
        if check_column(dataframe):
            error = check_column(dataframe)
            return jsonify(error), 400
        # save formatted dataframe
        if 'Confirmed' not in dataframe.columns:
            dataframe = format_data(dataframe)
        save_data(dataframe, client_id)
        # store file types by flag
        f_flag = dataframe.shape[1] < app.config['DISTINCT_NUM']
        f_type.append(f_flag)
    # handling file type exception
    if check_type(f_type):
        error = check_type(f_type)
        return jsonify(error), 400
    # construct json for frontend
    res = dict()
    res['client_id'] = client_id
    alarm, confirmed_num, accuracy = result_monitor(client_id)
    res['accuracy'] = accuracy
    res['total_alarm'] = alarm.shape[0]
    res['p_count'] = alarm.loc[alarm['RcaResult_Edited'] == 'P'].shape[0]
    res['c_count'] = alarm.loc[alarm['RcaResult_Edited'] == 'C'].shape[0]
    res['x_count'] = res['total_alarm'] - res['p_count'] - res['c_count']
    res['group_count'] = len(set(alarm['GroupId_Edited'].dropna()))
    res['confirmed'] = confirmed_num
    res['unconfirmed'] = res['group_count'] - res['confirmed']
    return jsonify(res)


@app.route('/switch', methods=['GET'])
def switch():
    x_alarm = request.args.get('xAlarm')
    client_id = request.headers.get('Client-Id')
    alarm = pd.read_csv(os.path.join(app.config['UPLOAD_FOLDER'], client_id,
                                     app.config['ALARM_FILE']))

    mask = pd.notnull(alarm['GroupId_Edited'])

    if x_alarm == 'true':
        mask = pd.isnull(alarm['GroupId_Edited'])
        update_tree(alarm)

    alarm = alarm.loc[mask]

    res = dict()
    res['start'] = pd.to_datetime(alarm['First'].min()).timestamp()
    res['end'] = pd.to_datetime(alarm['First'].max()).timestamp()
    return jsonify(res)


@app.route('/interval', methods=['GET'])
def interval():
    x_alarm = request.args.get('xAlarm')
    # get interval filtered dataframe
    a_time = datetime.fromtimestamp(int(request.args.get('start')))
    z_time = datetime.fromtimestamp(int(request.args.get('end')))
    alarm = interval_limit(a_time, z_time)
    # construct json for frontend
    res = dict()
    if x_alarm == 'false':
        res['group_id'] = list(alarm['GroupId_Edited']
                               .drop_duplicates()
                               .dropna())
    elif x_alarm == 'true':
        alarm = alarm.sort_values('X_Alarm')
        res['group_id'] = list(alarm['X_Alarm']
                               .drop_duplicates()
                               .dropna())
    return jsonify(res)


@app.route('/analyze', methods=['GET'])
def analyze():
    # generate topo tree
    group_id = request.args.get('groupId')
    alarm = group_filter(group_id)
    topo_path = ne2path(set(alarm['AlarmSource']))
    topo_tree = build_tree(topo_path)
    # construct json for frontend
    res = dict()
    res['topo'] = topo_tree
    res['table'] = json.loads(alarm.to_json(orient='records'))
    res['orange'] = list(set(alarm['AlarmSource']))
    return jsonify(res)


@app.route('/confirm', methods=['POST'])
def confirm():
    # save confirmed data
    client_id = request.headers.get('Client-Id')
    save_edit(client_id)
    # construct json for frontend
    res = dict()
    alarm, confirmed_num, accuracy = result_monitor(client_id)
    res['accuracy'] = accuracy
    res['total_alarm'] = alarm.shape[0]
    res['p_count'] = alarm.loc[alarm['RcaResult_Edited'] == 'P'].shape[0]
    res['c_count'] = alarm.loc[alarm['RcaResult_Edited'] == 'C'].shape[0]
    res['x_count'] = res['total_alarm'] - res['p_count'] - res['c_count']
    res['group_count'] = len(set(alarm['GroupId_Edited'].dropna()))
    res['confirmed'] = confirmed_num
    res['unconfirmed'] = res['group_count'] - res['confirmed']
    return jsonify(res)


@app.route('/expand', methods=['GET'])
def expand():
    # generate topo path
    group_id = request.args.get('groupId')
    # check intersection and update topo, table
    res = dict()
    res['yellow'] = []
    if not alarm.loc[alarm['GroupId_Edited'] != group_id].empty:
        alarm = alarm.loc[alarm['GroupId_Edited'] != group_id]
        add_path = ne2path(set(alarm['AlarmSource']))
        add_alarm = set()
        for path in add_path:
            add_ne = path2ne({path})
            if add_ne & topo_ne:
                topo_path = topo_path | {path}
                add_alarm = add_alarm | (add_ne & set(alarm['AlarmSource']))
        # construct json for frontend
        res['yellow'] = list(add_alarm)
        for ne in add_alarm:
            cur_alarm = alarm.loc[alarm['AlarmSource'] == ne]
            pre_alarm = pre_alarm.append(cur_alarm, ignore_index=True)
    topo_tree = build_tree(topo_path)
    res = dict()
    res['yellow'] = []
    res['topo'] = topo_tree
    res['table'] = json.loads(pre_alarm.to_json(orient='records'))
    return jsonify(res)


@app.route('/detail', methods=['GET'])
def detail():
    x_alarm = request.args.get('xAlarm')
    # get wrong and confirmed/unconfirmed groups
    column = 'Group_Edited'
    if x_alarm == 'true':
        column = 'X_Alarm'
    wrong, confirmed_group, unconfirmed_group = get_detail(column)
    # construct json for frontend
    res = dict()
    res['wrong'] = wrong
    res['confirmed'] = confirmed_group
    res['unconfirmed'] = unconfirmed_group
    return jsonify(res)


@app.route('/download', methods=['GET'])
def download():
    # get directory path
    client_id = request.args.get('clientId')
    dirpath = os.path.join(app.config['UPLOAD_FOLDER'], client_id)
    # generate file name
    filename = 'alarm-verified-' + str(int(time.time())) + '.csv'
    return send_from_directory(dirpath, 'alarm_format.csv', as_attachment=True,
                               attachment_filename=filename)


@app.route('/oneClick', methods=['POST'])
def one_click():
    x_alarm = request.args.get('xAlarm')
    client_id = request.headers.get('Client-Id')
    alarm = pd.read_csv(os.path.join(app.config['UPLOAD_FOLDER'], client_id,
                                     app.config['ALARM_FILE']))
    # confirm masked alarms
    mask = pd.notnull(alarm['GroupId_Edited'])
    if x_alarm == 'true':
        mask = pd.notnull(alarm['X_Alarm'])
    alarm.loc[mask, 'Confirmed'] = '1'
    # construct json for frontend
    res = dict()
    alarm, confirmed_num, accuracy = result_monitor(client_id)
    group_count = len(set(alarm['GroupId_Edited'].dropna()))
    res['accuracy'] = accuracy
    res['confirmed'] = confirmed_num
    res['unconfirmed'] = group_count - confirmed_num
    return jsonify(res)


@app.route('/cleanUp', methods=['POST'])
def clean_up():
    for dirname in os.listdir(app.config['UPLOAD_FOLDER']):
        # get directory path
        dirpath = os.path.join(app.config['UPLOAD_FOLDER'], dirname)
        # clean up cache regularly
        diff = time.time() - os.path.getmtime(dirpath)
        if diff > 7 * 24 * 60 * 60:
            shutil.rmtree(dirpath)


@app.errorhandler(500)
def error_500(exception):
    # construct json for frontend
    error = dict()
    error['code'] = 500
    error['message'] = '500 INTERNAL SERVER ERROR'
    return jsonify(error), 500
