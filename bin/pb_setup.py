# perfbase - (c) 2004-2005 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de>
#
# pb_setup - Set up a database for an experiment, or dump an XML experiment 
#            description for an existing database.
#
#     This file is part of perfbase.
#
#     perfbase is free software; you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation; either version 2 of the License, or
#     (at your option) any later version.
#
#     perfbase is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.
#
#     You should have received a copy of the GNU General Public License
#     along with perfbase; if not, write to the Free Software
#     Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

from pb_common import *
from pb_extend import *

import sys
import xml
import getopt
from os import F_OK, R_OK, getenv, access, popen4
from datetime import datetime
from xml.etree import ElementTree
from string import lower, find, count

# DBAPI implementation to access PostgreSQL
import psycopg2 as psycopg

# global variables in this module
exp_desc_xml = None
get_setup = False
do_force = False
exp_name = None
db_info = { 'host':None, 'port':None, 'name':None, 'user':None, 'password':None }

class pb_value:
    pass

    
def print_valid_dtypes():
    print "   Valid data types are:"
    for k, v in pb_valid_dtypes.iteritems():
        if k.find('(') < 0:
            print "    ", k
    print "   Size of datatype representation (in bytes) can be set via attribute 'size'"
    print "   for 'integer', 'float' and 'string'."
    

def print_help():
    """Print the specific help information for this tool."""
    print "perfbase setup - Set up a database for a new experiment"
    print "                 or retrieve experiment setup from database"
    print "Arguments:"
    print "--desc=<file>, -d <file>    XML experiment description is stored in <file>"
    print "--get, -g                   Retrieve experiment description from database"
    print "--force, -f                 Initialize experiment even if database does already exist"
    print "--exp=<exp>, -e <exp>       Get description of experiment <exp>"
    print_generic_dbargs()
    return


def build_unit_string(unit):
    global pb_valid_baseunits, pb_valid_scales, pb_scale_values

    frac = unit.find('fraction')
    if frac:
        dividend = frac.find('dividend')
        if not dividend:
            print "#* ERROR: no <dividend> in <fraction>."
            return None
        divisor = frac.find('divisor')
        if not divisor:
            print "#* ERROR: no <divisor> in <fraction>."
            return None
        dividend_str = build_unit_string(dividend)
        if dividend_str is None:
            print "#* ERROR: invalid <dividend> in <fraction>."
            return None
        if len(dividend_str) == 0:
            dividend_str = "1"
        divisor_str = build_unit_string(divisor)
        if divisor_str is None:
            print "#* ERROR: invalid <divisor> in <fraction>."
            return None
        return dividend_str + "/" + divisor_str

    prod = unit.find('product')
    if prod:
        factors = prod.findall('factor')
        if not factors:
            print "#* ERROR: no <factor> in <product>."
            return None
        product_str = None
        for f in factors:
            if product_str:
                product_str = product_str + "*"
            rval = build_unit_string(f)
            if not rval:
                return None
            product_str = product_str + rval
        return product_str

    base_unit = unit.find('base_unit')
    if base_unit is None:
        print "#* ERROR: no <base_unit> specified in <unit> leaf node."
        return None        
    base_str = base_unit.text
    if not base_str:
        base_str = "none"
    if not pb_valid_baseunits.has_key(base_str):
        print "#* ERROR: <base_unit> '%s' is an invalid base unit" % base_str
        print "   Valid base units are:"
        for k, v in pb_valid_baseunits.iteritems():
            print "\t%s\t\t%s" % (k, v)
        return None
    if base_str == 'none':
        # no unit, but may have scaling (like for MHz, which is Mega/s)
        base_str = ""

    scale_str = ""
    scale_node = unit.find('scaling')
    if not scale_node is None:
        scale_str = scale_node.text
        if not pb_valid_scales.has_key(scale_str):
            print "#* ERROR: <scaling> '%s' is an invalid scaling factor" % scale_str
            print "   Valid scaling factors are:"
            for k in pb_valid_scales.iterkeys():
                print "    %s" % k
            return None
        scale_str = pb_valid_scales[scale_str]
    return scale_str + base_str


def dump_experiment(filename):
    """ Dump an existing perfbase experiment into an XML description."""
    global exp_desc_xml, exp_name, get_setup, db_info

    # Open the output file and write the header
    if exp_name is None:
        print "#* ERROR: need to provide experiment name (option '--exp=...')"
        sys.exit(1)

    if be_verbose():
        print "#* Storing description of %s in %s " % (exp_name, filename)

    # Open the experiment database
    db_info['name'] = get_dbname(exp_name)
    get_dbserver(None, db_info)
    db = open_db(db_info, exp_name=exp_name)
    if db is None:
        sys.exit(1)
    if not check_db_version(db, exp_name):
        raise DatabaseError, "version mismatch of experiment database and commandline tools"    
    crs = db.cursor()    

    root_el = ElementTree.Element("experiment")

    # Get experiment meta data 
    sqlexe(crs, "SELECT * FROM exp_metadata")
    nim = build_name_idx_map(crs)
    row = crs.fetchone()
    
    expname_el = ElementTree.SubElement(root_el, "name")
    expname_el.text = row[nim['name']]

    info_el = ElementTree.SubElement(root_el, "info")
    performed_by_el = ElementTree.SubElement(info_el, "performed_by")
    name_el = ElementTree.SubElement(performed_by_el, "name")
    name_el.text = row[nim['creator']]
    if row[nim['organization']]:
        organization_el = ElementTree.SubElement(performed_by_el, "organization")
        organization_el.text = row[nim['organization']]

    synopsis_el = ElementTree.SubElement(info_el, "synopsis")
    synopsis_el.text = row[nim['synopsis']]
    description_el = ElementTree.SubElement(info_el, "description")
    description_el.text = row[nim['description']]
    if row[nim['project']]:
        project_el = ElementTree.SubElement(info_el, "project")
        project_el.text = row[nim['project']]

    # owner
    owner_el = ElementTree.SubElement(root_el, "owner")
    owner_el.text = row[nim['creator']]
    
    # Access right settings 
    for acc_type in ['admin_access', 'input_access', 'query_access']:
        sqlexe(crs, "SELECT * FROM exp_access WHERE acc_type = '%s'" % acc_type)
        nim = build_name_idx_map(crs)
        row = crs.fetchone()
        while row:
            acc_el = ElementTree.SubElement(root_el, acc_type)
            if row[nim['is_group']]:
                accname_el = ElementTree.SubElement(acc_el, 'group')
            else:
                accname_el = ElementTree.SubElement(acc_el, 'user')
            accname_el.text = row[nim['name']]
            
            row = crs.fetchone()        

    # Get all parameter values and result values, ordered alphabetically
    sqlexe(crs, "SELECT * FROM exp_values ORDER BY name ASC")
    nim = build_name_idx_map(crs)
    row = crs.fetchone()
    while row:
        val_type = "parameter"
        if row[nim['is_result']]:
               val_type = "result"
        val_el = ElementTree.SubElement(root_el, val_type)
        att = "multiple"
        if row[nim['only_once']]:
            att = "once"
        val_el.set('occurrence', att)

        valname_el = ElementTree.SubElement(val_el, 'name')
        valname_el.text = row[nim['name']]

        for n in ('synopsis', 'description'):
            if row[nim[n]]:
                n_el = ElementTree.SubElement(val_el, n)
                n_el.text = row[nim[n]]

        dt_el = ElementTree.SubElement(val_el, 'datatype')
        dt_el.text = row[nim['data_type']]

        if row[nim['default_content']] is not None:
            dflt_el = ElementTree.SubElement(val_el, 'default')
            dflt_el.text = row[nim['default_content']]

        if row[nim['valid_values']] is not None:
            for v in row[nim['valid_values']]:
                valid_el = ElementTree.SubElement(val_el, 'valid')
                valid_el.text = v.strip('"')

        # A lot of overhead is necesary to create the XML representation of
        # the data unit. Hmm.

        row = crs.fetchone()        

    # Write it out - sorry, the generated XML code is ugly, and no XML header is written.
    tree = ElementTree.ElementTree(root_el)
    if filename:
        tree.write(filename)
    else:
        # to stdout
        ElementTree.dump(tree)

    crs.close()
    db.close()
    
    return


def get_exp_xml_desc(xml_file):
    "Parse the XML-formatted experiment description"    
    if be_verbose():
        print "#* Parsing experiment description from ", xml_file

    if access(xml_file, F_OK|R_OK) == False:
        print "#* ERROR: can not access", xml_file
        sys.exit(1)
    exp_desc_tree = ElementTree.parse(xml_file)
    exp_desc_root = exp_desc_tree.getroot()

    # Do some sanity checks - real checking needs to be done based on the DTD (in advance)
    # and throughout the remaining parsing. 
    if exp_desc_root.tag != "experiment":
        print "#* ERROR: %s is not a perfbase experiment description." % (xml_file)
        sys.exit(1)

    return exp_desc_root


def add_value(db, crs, v):
    "Add a new value (XML Elementtree 'v') to database 'db'"
    if not cmp(v.tag, "result"):
        v_isresult = "True"
    else:
        v_isresult = "False"
    v_name = v.findtext('name')
    if not v_name:
        raise SpecificationError, "no <name> tag in experiment <parameter> or <result>!"

    # datatype
    dt_node = v.find('datatype')
    if dt_node is None:
        raise SpecificationError, "no <datatype> tag in experiment <parameter> or <result>!"
    v_dtype = dt_node.text
    if not pb_valid_dtypes.has_key(v_dtype):
        print_valid_dtypes()
        raise SpecificationError, "<datatype> '%s' is an invalid data type" % v_dtype
    att = dt_node.get('size')
    if att:
        if not att in ('2', '4', '8'):
            raise SpecificationError, "value '%s': <datatype> attribute 'size' has to be 2, 4 or 8" % v_name
        dt_size = '('+att+')'
    else:
        if v_dtype == 'string':
            dt_size = '(256)'
        else:
            dt_size = '(4)'
    if v_dtype in ('float', 'integer'):
        v_dtype += dt_size
    if v_dtype != 'string':
        sql_type = pb_valid_dtypes[v_dtype]
    else:
        sql_type = 'varchar'+dt_size
    
    v_term = v.find('unit')
    if v_term:
        v_unit = build_unit_string(v_term)
        if v_unit == None:
            raise SpecificationError, "invalid <term> in experiment <parameter> or <result>!"
    else:
        v_unit = ""

    v_synop = v.findtext('synopsis')
    if not v_synop:
        v_synop = ""
    v_desc = v.findtext('description')
    if not v_desc:
        v_desc = ""
    # If no <default> element is provided, a non-NULL constraint will be used for this
    # data column in all tables. If an empty <default> element is provided, the default content
    # will be NULL, which means that no constraint will be used.
    n_dflt = v.find('default')
    if n_dflt is not None:
        v_dflt = n_dflt.text
        if v_dflt is None:
            # empty <default> element
            v_dflt = ''
    else:
        # no <default> element provided
        v_dflt = None
    att = v.get('is_numeric')
    v_isnumeric = "False"
    if (att and not cmp(lower(att), 'yes')) or count(v_dtype, 'integer') > 0 or \
           count(v_dtype, 'float') > 0:
        v_isnumeric = "True"

    v_onlyonce = "False"
    att = v.get('occurrence')
    if not att:
        # remain backward compatible
    	att = v.get('occurence')
        if att and be_verbose():
            print "#* WARNING: found obsolete 'occurence' attribute - use 'occurrence' instead!"
    if (att and not cmp(lower(att), 'once')):
        v_onlyonce = "True"

    # list of valid values (managed as strings - does this always work for floats/integers?)
    valid_values = []
    valid_nodes = v.findall('valid')
    for v_n in valid_nodes:
        valid_values.append(v_n.text)
    if len(valid_values) > 0:
        if v_dflt and valid_values.count(v_dflt) == 0:
            raise SpecificationError, "<default> '%s' in parameter or result '%s' is not valid!" % (v_dflt, v_name)
        valid_val_str = "{ "
        for f in valid_values:
            valid_val_str += str(f) + ','
        valid_val_str = valid_val_str[:-1] + '}'

    sqlexe(crs, """INSERT INTO exp_values
        (name, data_type, sql_type, data_unit, synopsis,
        description, is_result, is_numeric, only_once)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""", None,
                (v_name, v_dtype, sql_type, v_unit, v_synop,
                 v_desc, v_isresult, v_isnumeric, v_onlyonce))
            
    if v_dflt is not None:
        sqlexe(crs, "UPDATE exp_values SET default_content = %s WHERE name = %s", None, (v_dflt, v_name))
    if len(valid_values) > 0:
        sqlexe(crs, "UPDATE exp_values SET valid_values = %s WHERE name = %s", None, (valid_val_str, v_name))

    # Check if we need to add a new column for this value to existing run tables.
    # We need to commit at this point to make sure that all pending transactions
    # are performed now. Otherwise, the potential error when inserting a value with
    # unknown SQL type would cancel them all.
    db.commit()
    sql_retry = True
    while sql_retry:
        try:
            if v_onlyonce != "True":
                sqlexe(crs, "SELECT * FROM run_metadata")
                nim = build_name_idx_map(crs)
                db_rows = crs.fetchall()
                # When creating a new experiment, a missing SQL datatype won't be
                # detected at this occasion. We need to test explicitely!
                if len(db_rows) == 0:
                    sqlexe(crs, "CREATE TABLE type_test (dummy %s)" % pb_valid_dtypes[v_dtype])
                    sqlexe(crs, "DROP TABLE type_test")

                sqlexe(crs, "ALTER TABLE rundata ADD COLUMN %s %s" % (v_name, pb_valid_dtypes[v_dtype]))
                if v_dflt is not None and len(v_dflt) > 0:
                    sql_cmd = "ALTER TABLE rundata ALTER COLUMN %s SET DEFAULT" % (v_name)
                    sql_cmd += " %s"
                    sqlexe(crs, sql_cmd, None, (v_dflt, ))
            else:
                sqlexe(crs, "ALTER TABLE rundata_once ADD COLUMN %s %s" % (v_name, pb_valid_dtypes[v_dtype]))
                if v_dflt is not None and len(v_dflt) > 0:
                    sql_cmd = "ALTER TABLE rundata_once ALTER COLUMN %s SET DEFAULT" % (v_name)
                    sql_cmd += " %s"
                    sqlexe(crs, sql_cmd, None, (v_dflt, ))
                if v_isresult == "False":
                    sqlexe(crs, "ALTER TABLE param_sets ADD COLUMN %s %s" % (v_name, pb_valid_dtypes[v_dtype]))
        except psycopg.ProgrammingError, error_msg:
            # Check if this error was caused by a missing datatype - if yes, add this datatype now.
            # This is a little bit hacky - how to determine a specific error reason by other means,
            # like a numeric error code?
            if error_msg.args[0].find(' type "%s" does not exist' % sql_type) >= 0:
                if eval("create_datatype_%s" % sql_type)(db, crs):
                    # Creating new datatype succeeded - retry!
                    continue
            raise DatabaseError, error_msg.args[0]
        sql_retry = False
    
    return


def drop_value(crs, v):
    "Drop a value 'v' from an experiment. This includes losing all data of this value."
    v_name = v.findtext('name')
    del_from_rundata = True

    sqlexe(crs, "SELECT * FROM exp_values WHERE name = %s", None, (v_name, ))
    nim = build_name_idx_map(crs)
    db_row = crs.fetchone()
    if db_row and db_row[nim['only_once']]:
        # This is a per-run value
        del_from_rundata = False
        sqlexe(crs, "ALTER TABLE rundata_once DROP COLUMN %s" % v_name)
        if not db_row[nim['is_result']]:
            sqlexe(crs, "ALTER TABLE param_sets DROP COLUMN %s" % v_name)
        
    sqlexe(crs, "DELETE FROM exp_values WHERE name = '%s'" % v_name)
    
    # Check if we need to drop a column of this value from existing run tables.
    if del_from_rundata:
        sqlexe(crs, "ALTER TABLE rundata DROP COLUMN %s" % (v_name))

    return


def setup_access_rights(xml_root, crs, current_user):
    """Set the access rights to the experiment database according to
    the experiment description."""

    # All perfbase users need to have the right to create temporary tables in the
    # database. Next to this, 'query' users do need SELECT rigths to all
    # tables. 'input' users additionally need INSERT rights to the 'run_metadata'
    # and 'rundata_once' tables, and need to be allowed to create persistent tables
    # (and set access rights to these tables).
    # Finally, 'admin' users need DELETE, UPDATE, and INSERT rights to the
    # 'exp_values' and 'exp_metadata' tables (and the same to the 'pb_perfbase' database).
    # The person that creates the experiment will always be an 'admin' user; all
    # other user information is derived from the experiment description and stored
    # within the experiment table 'exp_access'. This is necessary because we need to
    # set the access rights accordingly for each new run data table. The access control
    # itself is performed by the database server.
    # Create experiment description table.
    sqlexe(crs, """CREATE TABLE exp_access (
    name varchar(256),
    is_group boolean,
    acc_type varchar(32)
    )""")

    names = {}
    is_group = {}
    have_admin = False
    for t in ['input_access', 'query_access', 'admin_access']:
        node = xml_root.find(t)
        if node is None:
            continue
        for ug in ['group', 'user' ]:
            for elmt in node.findall(ug):                    
                if ug == 'group':
                    is_group[elmt.text] = True
                else:
                    is_group[elmt.text] = False
                if do_debug():
                    print "DEBUG: %s for %s (%s)" % (t, elmt.text, ug)
                names[elmt.text] = t
                if t == 'admin_access':
                    have_admin = True

    # At least the user that sets up the experiment needs to be admin!
    if not have_admin:
        names[current_user] = 'admin_access'
        is_group[current_user] = False

    for t in ['exp_metadata', 'run_metadata', 'exp_values', 'exp_access', 'rundata_once']:
        table_access_rights(crs, 'PUBLIC', False, t, 'REVOKE', 'ALL')

    for n, acc in names.iteritems():        
        sqlexe(crs, """INSERT INTO exp_access (name, is_group, acc_type) VALUES (%s, %s, %s)""",\
                    None, (n, is_group[n], acc))

        if acc == 'admin_access':
            for t in ['exp_metadata', 'run_metadata', 'exp_values', 'exp_access', 'rundata_once', \
                      'run_metadata_index_seq', 'param_sets', 'xml_files']:
                table_access_rights(crs, n, is_group[n], t, 'GRANT', 'ALL')
        elif acc == 'input_access':
            for t in ['exp_values',  'exp_access']:
                table_access_rights(crs, n, is_group[n], t, 'GRANT', 'SELECT')
            for t in ['exp_metadata' ]:
                table_access_rights(crs, n, is_group[n], t, 'GRANT', 'SELECT, UPDATE')
            for t in ['run_metadata', 'run_metadata_index_seq', 'rundata_once']:
                table_access_rights(crs, n, is_group[n], t, 'GRANT', 'INSERT, UPDATE, SELECT')
            for t in ['param_sets', 'xml_files']:
                # input users may create new parameter sets and xml files , but not change existing ones
                table_access_rights(crs, n, is_group[n], t, 'GRANT', 'INSERT, SELECT')
        else:
            # query users
            for t in ['exp_metadata', 'run_metadata', 'exp_values', 'exp_access', 'rundata_once',
                      'param_sets']:
                table_access_rights(crs, n, is_group[n], t, 'GRANT', 'SELECT')
            for t in ['xml_files']:
                # query users may store new xml files, but not change existing ones
                table_access_rights(crs, n, is_group[n], t, 'GRANT', 'SELECT, INSERT')
        
    return

def create_experiment(xml_file):
    """ Create a new perfbase experiment: set up the database"""
    global pb_db_version, pb_basedb
    global exp_name, get_setup, db_info, do_force

    exp_desc_root = get_exp_xml_desc(xml_file)
        
    # Determine the name of the experiment. Preference of the name:
    # cmdline > xml_file
    if exp_name is None:
        exp_name = exp_desc_root.findtext("name")
        if exp_name is None:
            print "#* ERROR: experiment name is not defined."
            sys.exit(1)
    if exp_name == "perfbase":
        print "#* ERROR: invalid experiment name 'perfbase' (used internally)."
        sys.exit(1)        
    db_info['name'] = lower("pb_"+exp_name);    
    owner = exp_desc_root.findtext("owner")
            
    get_dbserver(exp_desc_root, db_info)

    # Connect to, or if necessary create the new database.
    new_db = None
    try:
        new_db = psycopg.connect ("host=%s port=%d user=%s dbname=%s password=%s" % \
                                  (db_info['host'], db_info['port'], db_info['user'],
                                   db_info['name'], db_info['password']))
    except psycopg.Error, error_msg:
        # Here, we assume that the exception was caused by the non-existing database.
        # This is what we normally expect as we actually want to create a new database:
        # Create the database, and try again.        
        if be_verbose():
            print "#* Database '%s' does not exist - creating it." % db_info['name']
            if do_debug():
                print "   Reason:", error_msg
        if not create_db(db_info, owner):
            print "#* ERROR: Creating user database failed."
            sys.exit(1)

    # Now, try again
    if new_db is None:
        try:
            new_db = psycopg.connect ("host=%s port=%d user=%s dbname=%s password=%s" % \
                                      (db_info['host'], db_info['port'], db_info['user'],
                                       db_info['name'], db_info['password']))
        except psycopg.Error, error_message:
            print "#* ERROR: can not connect to user database '%s'." % db_info['name']            
            print error_message
            sys.exit(1)
    else:
        if not do_force:
            print "#* ERROR: database %s does already exist." % db_info['name']
            print "   Use the 'update' command to modify existing perfbase database. Exiting."
            new_db.close()
            sys.exit(1)
        else:
            print "#* WARNING: database %s does already exist. Initalizing it." % db_info['name']

    new_crs = new_db.cursor()
    sqlexe(new_crs, "COMMENT ON DATABASE %s IS '%s'" % (db_info['name'], pb_db_comment+exp_name))

    # Create experiment description table.
    try:
        sqlexe(new_crs, """CREATE TABLE exp_metadata (
        name varchar(256),
        creator varchar(256),
        organization varchar(256),
        project varchar(256),
        synopsis varchar(256),
        description text,
        created timestamp,
        last_modified timestamp,
        version integer
        )""")
    except psycopg.Error, error_msg:
        print error_msg
        print "#* ERROR: Could not create experiment meta table 'exp_meta'"
        new_crs.close()
        new_db.close()
        sys.exit(1)

    # Store the database meta description in both, the experiment database and the
    # perfbase meta-database. To do this, we need to extract the according information
    # from the XML description.
    if be_verbose():
        print "#* Parsing & storing meta data."
    
    dt = datetime(2004, 1, 1, 0, 0, 0)
    fmt = '%Y-%m-%d %H:%M:%S %Z%z'
    timestamp = dt.now().strftime(fmt)

    # Parse XML description to gather meta information.
    exp_elmt = exp_desc_root.find('info')
    cancel_setup = False
    if exp_elmt is None:
        print "#* ERROR: no <info> tag in experiment description!"
        cancel_setup = True
    exp_synop = exp_elmt.findtext('synopsis')
    if exp_synop is None:
        print "#* ERROR: no <synopsis> tag in experiment <info>!"
        cancel_setup = True
    exp_desc = exp_elmt.findtext('description')
    if exp_desc is None:
        print "#* ERROR: no <description> tag in experiment <info>!"
        cancel_setup = True
    exp_proj = exp_elmt.findtext('project')
    if exp_proj is None:
        exp_proj = ""    
    exp_elmt = exp_elmt.find('performed_by')
    if exp_elmt is None:
        print "#* ERROR: no <performed_by> tag in experiment <info>!"
        cancel_setup = True
    exp_creator = exp_elmt.findtext('name')
    if exp_creator is None:
        print "#* ERROR: no <name> tag in experiment <performed_by>!"
        cancel_setup = True
    exp_org = exp_elmt.findtext('organization')
    if exp_org is None:
        exp_org = ""

    if cancel_setup:
        print "#* Setting up the experiment failed. No database created."
        new_db.close()
        drop_db(db_info)
        sys.exit(1);

    # This table stores information on all result values and parameter values 
    try:
        if be_verbose():
            print "#* Creating experiment values index table."
        sqlexe(new_crs, """CREATE TABLE exp_values (
        index serial,
        name varchar(256) UNIQUE,
        data_type varchar(256),
        sql_type varchar(256),
        data_unit varchar(256),
        default_content varchar(256),
        synopsis varchar(256),
        description text,
        is_result boolean,
        is_numeric boolean,
        only_once boolean,
        valid_values varchar(256)[]
        )""")

        # This table stores information on all runs of the experiment 
        if be_verbose():
            print "#* Creating experiment run data index table."
        sqlexe(new_crs, """CREATE TABLE run_metadata (
        index serial,
        creator varchar(256),
        created timestamp,
        performed timestamp,
        key integer UNIQUE,
        data text,
        active boolean,
        synopsis varchar(256),
        description text,
        input_hash bigint[],
        input_name varchar(1024)[],
        input_mtime timestamp[],
        nbr_inputs integer
        )""")

        if be_verbose():
            print "#* Creating experiment global values data table."
        sqlexe(new_crs, "CREATE TABLE rundata ( pb_run_index integer)")
        sqlexe(new_crs, "CREATE INDEX idx_id_rundata ON rundata(pb_run_index)")

        # Next to the 'rundata' table which stores repeated mutil-value datasets of all runs, we
        # need another table 'rundata_once' which stores the constant values of a run (paramaters
        # or results that do not change). One row per run, indexed via the run index, will be created.
        if be_verbose():
            print "#* Creating experiment per-run-values data table."
        sqlexe(new_crs, "CREATE TABLE rundata_once ( run_index integer UNIQUE)")

        # 'param_sets' stores named sets of parameters that can be used when importing new data.
        if be_verbose():
            print "#* Creating experiment  table for named parameter sets."
        sqlexe(new_crs, "CREATE TABLE param_sets ( set_name varchar(256) UNIQUE )")
        
        # This table stores XML files like queries etc.
        if be_verbose():
            print "#* Creating experiment XML file table."
        sqlexe(new_crs, """CREATE TABLE xml_files (
        creator varchar(256),
        created timestamp,
        filename varchar(256),
        name varchar(64) UNIQUE,
        type varchar(16),
        synopsis varchar(256),
        description text,
        xml text
        )""")

    except DatabaseError, error_msg:
        print "#* ERROR: could create all required experiment tables."
        print "   ", error_msg
        print "#* Setting up the experiment failed. No database created."
        new_db.close()
        drop_db(db_info)
        sys.exit(1);

    # Now parse the XML file for all <parameter>s and <result>s, and put the data in 'exp_values'.
    exp_parms = exp_desc_root.findall('parameter')
    exp_rslts = exp_desc_root.findall('result')
    for r in exp_rslts:
        exp_parms.append(r)
    setup_failed = False
    for v in exp_parms:
        try:
            add_value(new_db, new_crs, v)
        except SpecificationError, error_msg:
            print "#* ERROR: could not parse value specification for value '%s'" % v.findtext('name')
            print "   ", error_msg
            setup_failed = True
        except psycopg.Error, error_msg:
            print "#* ERROR: could not add value '%s' to database!" % v.findtext('name')
            print "   ", error_msg
            setup_failed = True
        except DatabaseError, error_msg:
            print "#* ERROR: could not add value '%s' to database!" % v.findtext('name')
            print "   ", error_msg
            setup_failed = True
        if setup_failed:
            print "#* Setting up the experiment failed. No database created."
            new_db.close()
            drop_db(db_info)
            sys.exit(1);

    # Finally, store the experiment metadata in both databases, the experiment database
    # itself and the meta database.
    try:
        sqlexe(new_crs, """INSERT INTO exp_metadata
        (name, creator, organization, project, synopsis, description, created, last_modified, version)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""", None, 
                    (exp_name, exp_creator, exp_org, exp_proj, exp_synop, exp_desc, \
                     timestamp, timestamp, pb_db_version))
        setup_access_rights(exp_desc_root, new_crs, db_info['user'])
    except psycopg.Error, error_msg:
        print error_msg
        print "#* Setting up the experiment failed. No database created."
        new_crs.close()
        new_db.close()
        drop_db(db_info)
        sys.exit(1)               

    new_db.commit()
    new_crs.close()
    new_db.close()

    # Done.
    if be_verbose():
        print "#* Experiment '%s' was successfully created." % exp_name

    return


def parse_cmdline(argv):
    """Set default values for externally controled parameters, and set them according to parameters."""
    global exp_desc_xml, exp_name, get_setup, do_force
    global db_info

    # set defaults
    exp_desc_xml = None
    get_setup = False
  
    argv2 = argv_preprocess(argv)
    n_params = param_count(argv2)

    # parse arguments
    try:
        options, values = getopt.getopt(argv2, 'hVvd:gfe:', ['dbhost=', 'dbport=', 'dbuser=', 'dbpasswd=',
                                                             'help', 'version', 'verbose', 'desc=', 'get',
                                                             'exp=', 'force', 'debug', 'sqltrace'])
    except getopt.GetoptError, error_msg:
        print "#* ERROR: Invalid argument found:", error_msg
        print "   Use option '--help' for a list of valid arguments."
        sys.exit(1)

    for o, v in options:
        if o in ("-v", "--verbose"):
            set_verbose(True)
            continue
        if o in ("-h", "--help"):
            print_help()
            sys.exit(0)
        if o in ("--version", "-V"):
            print_version()
            sys.exit(0)
        if o == "--debug":
            set_debug(True)
            continue
        if o == "--sqltrace":
            set_sql_trace(True)
            continue

        if o in ("-d", "--desc"):
            exp_desc_xml = v
            continue
        if o in ("-e", "--exp"):
            exp_name = v
            continue
        if o in ("-g", "--get"):
            get_setup = True
            continue
        if o in ("-f", "--force"):
            do_force = True
            continue

        if o == "--dbhost":
            db_info['host'] = v
            continue
        if o == "--dbport":
            db_info['port'] = v
            continue
        if o == "--dbuser":
            db_info['user'] = v
            continue
        if o == "--dbpasswd":
            db_info['password'] = v
            continue

    if exp_desc_xml == None and not get_setup:
        print "#* ERROR: no experiment description specified"
        print_help()
        sys.exit(1)
    return True


def main(argv=None):
    global exp_desc_xml
    
    if argv is None:
        argv = sys.argv[1:]   
    if not parse_cmdline(argv):
        return 

    if get_setup:
        # dump experiment setup to an XML file
        dump_experiment(exp_desc_xml)
    else:
        # Create a new experiment
        try:
            create_experiment(exp_desc_xml)
        # XXX Is there no better XML parse exception to catch!?
        except xml.parsers.expat.ExpatError, error_msg:
            print "#* ERROR: XML parse error in experiment description '%s'" % exp_desc_xml
            print "  ", error_msg
            sys.exit(1)
    return


if __name__ == "__main__":
    run_mode = getenv("PB_RUNMODE")
    if run_mode == "debug":
        main()
    else:
        try:
            main()
        except KeyboardInterrupt:
            print ""
            print "#* User aborted setup operation. No data written to database."
        except psycopg.ProgrammingError, error_msg:
            if error_msg.args[0].find('permission denied') > 0:
                print "#* ERROR: user '%s' has insufficient privileges to access experiment '%s'" \
                      % (db_info['user'], exp_name)
            else:
                print "#*", error_msg
            sys.exit(1)
        except DatabaseError, error_msg:
            print "#* Could not access any data."
            print " ", error_msg
            sys.exit(1)
        except StandardError, error_msg:
            print "#* ERROR: Abort by exception:"
            print "  ", error_msg
            sys.exit(1)
    sys.exit(0)
