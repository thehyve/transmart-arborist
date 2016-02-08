import os
from collections import OrderedDict

from flask import Flask, request, redirect, url_for, render_template, json, \
 Response, send_from_directory
from werkzeug import secure_filename

import urllib
from markupsafe import Markup

from functions.params import Study_params, Clinical_params, get_study_id
from functions.exceptions import HyveException, HyveIOException
from functions.clinical import columns_to_json, json_to_columns, getchildren, \
                               get_datafiles, get_column_map_file, \
                               add_to_column_file, get_word_map
from functions.feedback import get_feedback_dict, merge_feedback_dicts

STUDIES_FOLDER = 'studies'
ALLOWED_EXTENSIONS = set(['txt', 'tsv'])

app = Flask(__name__)
app.jinja_env.add_extension("jinja2.ext.do")
app.jinja_env.trim_blocks = True
app.jinja_env.lstrip_blocks = True
app.jinja_env.filters['path_join'] = lambda paths: os.path.join(*paths)

if not os.path.isdir(STUDIES_FOLDER):
    os.mkdir(STUDIES_FOLDER)

possible_datatypes = ['study', 'clinical']


@app.template_filter('urlencode')
def urlencode_filter(s):
    ''' Necessary addition to Jinja2 filters, to escape chars for in url '''
    if type(s) == 'Markup':
        s = s.unescape()
    s = s.encode('utf8')
    s = urllib.quote_plus(s)
    return Markup(s)


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1] in ALLOWED_EXTENSIONS


@app.route('/')
def index():
    studiesfolder = os.path.abspath(STUDIES_FOLDER)
    studiesfolder = studiesfolder.strip('/')
    return redirect(url_for('studies_overview', studiesfolder=studiesfolder))


@app.route('/folder/create/', defaults={'studiesfolder': ''}, methods=['POST'])
@app.route('/folder/<path:studiesfolder>/create/', methods=['POST'])
def create_folder(studiesfolder):
    studiesfolder = '/'+studiesfolder
    if 'foldername' in request.form:
        foldername = os.path.join(studiesfolder,
                                  request.form['foldername'])
        if not os.path.exists(foldername):
            os.mkdir(foldername)

    studiesfolder = studiesfolder.strip('/')

    return redirect(url_for('studies_overview', studiesfolder=studiesfolder))


@app.route('/folder/', defaults={'studiesfolder': ''})
@app.route('/folder/<path:studiesfolder>/')
def studies_overview(studiesfolder):
    studiesfolder = '/'+studiesfolder
    parentfolder = os.path.abspath(os.path.join(studiesfolder, os.pardir))
    studies = {}

    for file in os.listdir(studiesfolder):
        filepath = os.path.join(studiesfolder, file)
        if os.path.isdir(filepath) and not file.startswith('.'):
            studies[file] = {'type': 'folder'}
            studyparamsfile = os.path.join(filepath, 'study.params')
            clinicalparamsfile = os.path.join(filepath, 'clinical.params')
            if os.path.exists(studyparamsfile) or \
                    os.path.exists(clinicalparamsfile):
                studies[file]['type'] = 'study'
    orderedstudies = OrderedDict(sorted(studies.items(),
                                        key=lambda x: x[0].lower()))

    studiesfolder = studiesfolder.strip('/')
    parentfolder = parentfolder.strip('/')

    return render_template('studiesoverview.html',
                           studiesfolder=studiesfolder,
                           parentfolder=parentfolder,
                           studies=orderedstudies)


@app.route('/folder/s/<study>/', defaults={'studiesfolder': ''})
@app.route('/folder/<path:studiesfolder>/s/<study>/')
def study_page(studiesfolder, study):
    studiesfolder = '/'+studiesfolder

    paramsdict = {}

    for datatype in possible_datatypes:

        paramsfile = os.path.join(studiesfolder, study, datatype+'.params')
        paramsdict[datatype] = {}
        feedback = get_feedback_dict()

        if os.path.exists(paramsfile):
            paramsdict[datatype]['exists'] = True
            if datatype == 'study':
                paramsobject = Study_params(paramsfile)
            elif datatype == 'clinical':
                paramsobject = Clinical_params(paramsfile)
            else:
                feedback['errors'].append('Params file {} not supported'.
                                          format(paramsfile))
        else:
            paramsdict[datatype]['exists'] = False
            feedback['errors'].append('No {} found'.
                                      format(datatype+'.params'))

        params = {}
        try:
            paramsobject
        except NameError:
            pass
        else:
            params = paramsobject.get_variables()
            params_feedback = paramsobject.get_feedback()
            feedback = merge_feedback_dicts(feedback, params_feedback)
            params = OrderedDict(sorted(params.items(),
                                 key=lambda x: x[0].lower()))

        paramsdict[datatype]['params'] = params
        paramsdict[datatype]['feedback'] = feedback

    studiesfolder = studiesfolder.strip('/')

    return render_template('studypage.html',
                           studiesfolder=studiesfolder,
                           study=study,
                           paramsdict=paramsdict,
                           possible_datatypes=possible_datatypes)


@app.route(('/folder/<path:studiesfolder>/s/<study>/clinical/create/'))
def create_mapping_file(studiesfolder, study):
    studiesfolder = '/'+studiesfolder
    columnmappingfile = 'COLUMN_MAP_FILE'
    wordmappingfile = 'WORD_MAP_FILE'

    mappingfile = request.args['variable']

    if mappingfile not in [columnmappingfile, wordmappingfile]:
        return

    studyid = get_study_id(studiesfolder, study)

    datatypepath = os.path.join(studiesfolder, study, 'clinical')
    if not os.path.exists(datatypepath):
        os.mkdir(datatypepath)

    mappingfilename = studyid+'_'+mappingfile+'.tsv'
    mappingfilepath = os.path.join(datatypepath, mappingfilename)
    if not os.path.exists(mappingfilepath):
        with open(mappingfilepath, "w+") as handle:
            tree = {}
            if mappingfile == columnmappingfile:
                mappingfiledata, feedback = json_to_columns(tree=tree)
            elif mappingfile == wordmappingfile:
                mappingfiledata = get_word_map()
            handle.write(mappingfiledata)

    return json.jsonify(mappingfilename=mappingfilename)


@app.route('/folder/<path:studiesfolder>/s/<study>/params/<datatype>/create/')
def create_params(studiesfolder, study, datatype):
    studiesfolder = '/'+studiesfolder
    feedback = get_feedback_dict()
    paramsfile = os.path.join(studiesfolder, study, datatype+'.params')

    if not os.path.exists(paramsfile):
        with open(paramsfile, "w+"):
            pass
    if datatype != 'study':
        datatypepath = os.path.join(studiesfolder, study, datatype)
        if not os.path.exists(datatypepath):
            os.mkdir(datatypepath)

    studiesfolder = studiesfolder.strip('/')
    return redirect(url_for('edit_params',
                            studiesfolder=studiesfolder,
                            study=study,
                            datatype=datatype))


@app.route('/folder/<path:studiesfolder>/s/<study>/params/<datatype>/',
           methods=['GET', 'POST'])
def edit_params(studiesfolder, study, datatype):
    studiesfolder = '/'+studiesfolder
    feedback = get_feedback_dict()
    paramsfile = os.path.join(studiesfolder, study, datatype+'.params')

    if request.method == 'POST':
        if os.path.exists(paramsfile):
            if datatype == 'study':
                paramsobject = Study_params(paramsfile)
            elif datatype == 'clinical':
                paramsobject = Clinical_params(paramsfile)
            else:
                feedback['errors'].append('Params file {} not supported'.
                                          format(paramsfile))
        else:
            feedback['errors'].append('Params file {} does not exist'.
                                      format(paramsfile))

        try:
            paramsobject
        except NameError:
            pass
        else:
            for variable in request.form:
                paramsobject.update_variable(variable,
                                             request.form[variable])
            app.logger.debug(paramsobject.get_variables())
            paramsobject.save_to_file()
            feedback = paramsobject.get_feedback()

    if os.path.exists(paramsfile):
        if datatype == 'study':
            paramsobject = Study_params(paramsfile)
        elif datatype == 'clinical':
            paramsobject = Clinical_params(paramsfile)
        else:
            feedback['errors'].append('Params file {} not supported'.
                                      format(paramsfile))
    else:
        feedback['errors'].append('Params file {} does not exist'.
                                  format(paramsfile))

    params = {}
    variables = {}
    try:
        paramsobject
    except NameError:
        feedback['errors'].append('No params file loaded')
    else:
        variables = paramsobject.get_possible_variables()
        params = paramsobject.get_variables()

        for variable in variables:
            if variable in params:
                    variables[variable]['value'] = params[variable]

        params_feedback = paramsobject.get_feedback()
        feedback = merge_feedback_dicts(feedback, params_feedback)

    variables = OrderedDict(sorted(variables.items(),
                                   key=lambda x: x[0].lower()))

    studiesfolder = studiesfolder.strip('/')

    return render_template('params.html',
                           studiesfolder=studiesfolder,
                           study=study,
                           datatype=datatype,
                           variables=variables,
                           feedback=feedback)


@app.route('/folder/<path:studiesfolder>/s/<study>/tree/')
def edit_tree(studiesfolder, study):
    studiesfolder = '/'+studiesfolder

    columnsfile = get_column_map_file(studiesfolder, study)
    if columnsfile is not None:
        json = columns_to_json(columnsfile)
        clinicaldatafiles = get_datafiles(columnsfile)
    else:
        json = {}
        clinicaldatafiles = []

    studiesfolder = studiesfolder.strip('/')

    return render_template('tree.html',
                           studiesfolder=studiesfolder,
                           clinicaldatafiles=clinicaldatafiles,
                           study=study,
                           json=json)


@app.route('/folder/<path:studiesfolder>/s/<study>/tree/add/',
           methods=['POST'])
def add_datafile(studiesfolder, study):
    studiesfolder = '/'+studiesfolder
    file = request.files['file']

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        datafilepath = os.path.join(studiesfolder, study, 'clinical', filename)
        if not os.path.exists(datafilepath):
            file.save(datafilepath)
            columnmappingfilepath = get_column_map_file(studiesfolder, study)
            if columnmappingfilepath is not None:
                add_to_column_file(datafilepath, columnmappingfilepath)
            else:
                print "no columnmappingfile"
        else:
            print "file already exists"
    else:
        print "file not allowed"

    studiesfolder = studiesfolder.strip('/')
    return redirect(url_for('edit_tree',
                            studiesfolder=studiesfolder,
                            study=study))


@app.route('/folder/<path:studiesfolder>/s/<study>/tree/save_columnsfile/',
           methods=['POST'])
def save_columnsfile(studiesfolder, study):
    studiesfolder = '/'+studiesfolder
    feedback = get_feedback_dict()

    tree = request.get_json()
    tree, feedback_json_to_columns = json_to_columns(tree)

    feedback = merge_feedback_dicts(feedback, feedback_json_to_columns)

    columnsfile = get_column_map_file(studiesfolder, study)
    if columnsfile is not None:
        columnmappingfile = open(columnsfile, 'wb')
        columnmappingfile.write(tree)
        columnmappingfile.close()

        feedback['infos'].append('Saved column mapping file \'{}\'.'.format(
            os.path.split(columnsfile)[1]))
    else:
        feedback['errors'].append('No params file loaded')

    return json.jsonify(feedback=feedback)


@app.errorhandler(404)
def errorhandler(e):
    code = 404
    return render_template('error.html', error=str(e), code=code), code


@app.errorhandler(403)
def errorhandler(e):
    code = 403
    return render_template('error.html', error=str(e), code=code), code


@app.errorhandler(405)
def errorhandler(e):
    code = 405
    return render_template('error.html', error=str(e), code=code), code


@app.errorhandler(410)
def errorhandler(e):
    code = 410
    return render_template('error.html', error=str(e), code=code), code


@app.errorhandler(500)
def errorhandler(e):
    code = 500
    return render_template('error.html', error=str(e), code=code), code

if __name__ == '__main__':
    app.debug = True
    app.run()
