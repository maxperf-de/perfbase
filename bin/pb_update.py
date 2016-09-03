# perfbase - (c) 2004-2006 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de>
#
# pb_update - Change an experiment according to the experiment update description.
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
from pb_setup import *

import sys
import xml
import getopt
from os import F_OK, R_OK, getenv, access, popen4
from datetime import datetime
from xml.etree import ElementTree
from string import lower, find, count

updt_desc_xml = None
exp_name = None
db_info = { 'host':None, 'port':None, 'name':None, 'user':None, 'password':None }


def print_help():
    """Print the specific help information for this tool."""
    print "perfbase update - Modify the definition of an experiment."
    print ""                 
    print "Arguments:"
    print "--desc=<file>, -d <file>    XML experiment update description is stored in <file>"
    print_generic_dbargs()
    return


def parse_cmdline(argv):
    """Set default values for externally controled parameters, and set them according to parameters."""
    global updt_desc_xml, exp_name
    global db_info

    # set defaults
    updt_desc_xml = None
  
    argv2 = argv_preprocess(argv)
    n_params = param_count(argv2)

    # parse arguments
    try:
        options, values = getopt.getopt(argv2, 'hVvd:', ['dbhost=', 'dbport=', 'dbuser=', 'dbpasswd=',
                                                         'help', 'version', 'verbose', 'desc=', 'debug',
                                                         'sqltrace'])
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
            updt_desc_xml = v
            continue

        if o == "--dbhost":
            db_info['host'] = v
            continue
        if o == "--dbport":
            db_info['port'] = v
            continue
        if o == "--dbname":
            exp_name = v
            continue
        if o == "--dbuser":
            db_info['user'] = v
            continue
        if o == "--dbpasswd":
            db_info['password'] = v
            continue

    if updt_desc_xml == None:
        print "#* ERROR: no experiment update description specified"
        print_help()
        sys.exit(1)
    return True


def get_exp_xml_desc(xml_file):
    "Parse the XML-formatted experiment description"
    
    if be_verbose():
        print "#* Parsing experiment update description from ", xml_file

    if access(xml_file, F_OK|R_OK) == False:
        print "#* ERROR: can not access", xml_file
        sys.exit(1)
    exp_desc_tree = ElementTree.parse(xml_file)
    exp_desc_root = exp_desc_tree.getroot()

    # Do some sanity checks - real checking needs to be done based on the DTD (in advance)
    # and throughout the remaining parsing. 
    if exp_desc_root.tag != "experiment_update":
        print "#* ERROR: %s is not a perfbase experiment update description." % (xml_file)
        sys.exit(1)

    return exp_desc_root


def update_value(crs, v):
    "Change the characteristics of a value (XML Elementtree 'v') in epxeriment database 'db'"

    # In contrast to 'add_value()', not all attributes of a value need to be provided
    # here, but only the attributes which will change.
    v_name = v.findtext('name')
    if not v_name:
        raise SpecificationError, "no <name> tag in experiment <parameter> or <result>!"
    current_v_name = v_name
    sqlexe(crs, "SELECT * FROM exp_values WHERE name = %s", None, (v_name, ))
    val_nim = build_name_idx_map(crs)
    if crs.rowcount == 0:
        raise SpecificationError, "Invalid <name> '%s' (not defined in experiment)" % v_name
    val_row = crs.fetchone()
    
    # First, change the attributes of the value in the 'exp_values' table.
    v_new_name = v.findtext('new_name')
    if v_new_name and cmp(v_new_name, v_name):
        sqlexe(crs, "UPDATE exp_values SET name = '%s' WHERE name = '%s'" % (v_new_name, v_name))
        if val_row[val_nim['only_once']]:
            sqlexe(crs, "ALTER TABLE rundata_once RENAME COLUMN %s TO %s" % (v_name, v_new_name))
            if not val_row[val_nim['is_result']]:
                sqlexe(crs, "ALTER TABLE param_sets RENAME COLUMN %s TO %s" % (v_name, v_new_name))
        current_v_name = v_new_name
        
    v_dtype = v.findtext('datatype')
    if v_dtype and not pb_valid_dtypes.has_key(v_dtype):
        print_pb_valid_dtypes()
        raise SpecificationError, "<datatype> '%s' is an invalid data type" % v_dtype
    if v_dtype and v_dtype != val_row[val_nim['data_type']]:
        # Changing the datatype is not supported yet (as SQL does not support it - we'll
        # have to do some tricks to achieve this without losing the data).
        # PostgreSQL 8.0 is said to support this!
        print "#* ERROR: Changing the datatype of a value is not yet supported."
        print "   Ignoring this change request, but performing remaining changes."

    v_unitterm = v.find('unit')
    if v_unitterm:
        v_unit = build_unit_string(v_unitterm)
        if v_unit != None and v_unit != val_row[val_nim['data_unit']]:
            sqlexe(crs, "UPDATE exp_values SET data_unit = %s WHERE name = %s", None, (v_unit, current_v_name))

    v_synop = v.findtext('synopsis')
    if v_synop != None and v_synop != val_row[val_nim['synopsis']]:
        sqlexe(crs, "UPDATE exp_values SET synopsis = %s WHERE name = %s", None, (v_synop, current_v_name))

    v_desc = v.findtext('description')
    if v_desc != None and v_desc != val_row[val_nim['description']]:
        sqlexe(crs, "UPDATE exp_values SET description = %s WHERE name = %s", None,(v_desc, current_v_name))

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
    if v_dflt != None:
        sql_type = val_row[val_nim['sql_type']]
        if v_dflt != val_row[val_nim['default_content']]:
            sqlexe(crs, "UPDATE exp_values SET default_content = %s WHERE name = %s", None, (v_dflt, current_v_name))
            if val_row[val_nim['only_once']] and len(v_dflt) > 0:
                sqlexe(crs, "ALTER TABLE rundata_once ALTER COLUMN %s SET DEFAULT %s" % (current_v_name,
                                                                                         quote_value(val_row,
                                                                                                     val_nim,
                                                                                                     v_dflt)))
    v_isresult = (v.tag == "result")
    if (v_isresult and not val_row[val_nim['is_result']]) or (not v_isresult and val_row[val_nim['is_result']]):
        if v_isresult:
            bool_str = "True"
        else:
            bool_str = "False"
        sqlexe(crs, "UPDATE exp_values SET is_result = %s WHERE name = %s", None, (bool_str, current_v_name))

    # List of valid values (managed as strings - does this always work for floats/integers?).
    # When updating, the new values are added to the existing ones. This does not allow to delete
    # existing valid values, but this is a bit more complicated anyway: we would have to check all
    # runs if such a valid does not yet exist to avoid inconsistencies.
    valid_values = []
    valid_nodes = v.findall('valid')
    for v_n in valid_nodes:
        valid_values.append(v_n.text)
    if len(valid_values) > 0:
        sqlexe(crs, "SELECT valid_values FROM exp_values WHERE name = %s", None, (current_v_name, ))
        nim = build_name_idx_map(crs)
        db_row = crs.fetchone()
        if db_row[nim['valid_values']] != None:
            # retrieve existing values from string of format {..,..,..}
            valid_values.extend(db_row[nim['valid_values']])
        valid_val_str = "{ "
        for f in valid_values:
            valid_val_str += str(f) + ','
        valid_val_str = valid_val_str[:-1] + '}'
        sqlexe(crs, "UPDATE exp_values SET valid_values = %s WHERE name = %s", None, (valid_val_str, current_v_name))
    
    if not val_row[val_nim['only_once']]:
        # Now, propagate changes into existing run tables.
        # Here, come tricky code to change the type of a column would need to be inserted.
        # Actually, this will require a DROP & ADD cycle, and re-inserting (casted) values
        # from the table afterwards. We save this for later.
        # For now, just change or drop the default value.
        if v_dflt is None or len(v_dflt) == 0:
            sql_cmd = "ALTER TABLE rundata ALTER COLUMN %s DROP DEFAULT" % (v_name)
        else:
            sql_cmd = "ALTER TABLE rundata ALTER COLUMN %s SET DEFAULT %s" % (v_name, mk_sql_const(sql_type, v_dflt))
        sqlexe(crs, sql_cmd)

        if v_new_name and cmp(v_new_name, v_name):
            # Rename the column for this value.
            sqlexe(crs, "ALTER TABLE rundata RENAME COLUMN %s TO %s" % (v_name, v_new_name))

    return


def update_experiment(xml_file):
    """Update an existing perfbase experiment"""
    global exp_name, db_info
    global pb_valid_dtypes

    exp_desc_root = get_exp_xml_desc(xml_file)
        
    # Determine the name of the experiment. Preference of the name:
    # cmdline > xml_file
    if exp_name is None:
        exp_name = exp_desc_root.findtext("experiment")
        if exp_name is None:
            print "#* ERROR: experiment name is not defined (tag <experiment> not found)."
            sys.exit(1)

    db_info['name'] = get_dbname(exp_name)           
    get_dbserver(exp_desc_root, db_info)

    # Open the databases.
    exp_db = None
    try:
        exp_db = psycopg.connect ("host=%s port=%d user=%s dbname=%s password=%s" % \
                                  (db_info['host'], db_info['port'], db_info['user'],
                                   db_info['name'], db_info['password']))        
        if not check_db_version(exp_db, exp_name):
            raise DatabaseError, "version mismatch of experiment database and commandline tools"    
    except psycopg.Error, error_msg:
        print "#* Can not access experiment %s on %s:%d" % (exp_name, db_info['host'], db_info['port'])
        print "   Reason:", error_msg
        sys.exit(1)
    exp_crs = exp_db.cursor()

    # Parse XML description to gather meta information. Not all of the information
    # needs to exist in the XML description - information that is not found in the
    # description will remain unchanged in the experiment.
    exp_elmt = exp_desc_root.find('info')
    if exp_elmt:
        info_tags = ['synopsis', 'description', 'project' ]
        for tag in info_tags:
            tag_text = exp_elmt.findtext(tag)
        if tag_text:
            sqlexe(exp_crs, "UPDATE exp_metadata SET %s = '%s' WHERE name = '%s'" % (tag, tag_text, exp_name))
        exp_elmt = exp_elmt.find('performed_by')
        if exp_elmt:
            creator_tags = ['name', 'organization']
            for tag in creator_tags:
                tag_text = exp_elmt.findtext(tag)
                if tag_text:
                    sqlexe(exp_crs, "UPDATE exp_metadata SET %s = %s WHERE name = %s",
                           None, (tag, tag_text, exp_name))

    # Values may have been added or removed. First, this has to be detected. Then, for
    # an added value, add it to the 'exp_values' table *and* add a column to all existing
    # run tables. If a value has been removed, we need to remove it from the 'exp_values'
    # table, then remove the respective column in all run tables.
    # Potential problem: we should lock the database for all these transactions - or perform
    # them atomically. Can this be achieved by commit()'ing only once at the very end?

    # Build a dictionary of all current values in the experiment.
    exp_values = {}
    sqlexe(exp_crs, "SELECT * FROM exp_values")
    nim = build_name_idx_map(exp_crs)
    db_rows = exp_crs.fetchall()
    for db_row in db_rows:
        exp_values[db_row[nim['name']]] = db_row
    
    # Now gather all values from the experiment (update) description to
    # match the experiment database with the update description
    desc_parms = exp_desc_root.findall('parameter')
    desc_rslts = exp_desc_root.findall('result')
    for r in desc_rslts:
        desc_parms.append(r)
    try:
        for v in desc_parms:
            v_name = v.findtext('name')
            if not v_name:
                raise SpecificationError, "<name> tag missing for value"
            if not exp_values.has_key(v_name):
                # this is a new value
                if be_verbose():
                    print "#* adding new value '%s'" % v_name
                add_value(exp_db, exp_crs, v)
            else:
                # change, replace  or delete existing value
                replace = False
                drop = False
                att = v.get('action')
                if att:
                    if lower(att) == 'replace':
                        replace = True
                    elif lower(att) == 'drop':
                        drop = True
                    elif not lower(att) == 'auto':
                        raise SpecificationError, "invalid content '%s' to attribute 'action'" % att

                if drop or replace:
                    if be_verbose():
                        print "#* dropping value '%s'" % v_name
                    try:
                        drop_value(exp_crs, v)
                    except DatabaseError, error_msg:
                        print "#* ERROR: could not drop value from database!"
                        print "   ", error_msg
                        sys.exit(1);
                    if replace:
                        if be_verbose():
                            print "#* adding new value '%s'" % v_name
                        add_value(exp_db, exp_crs, v)
                else:
                    if be_verbose():
                        print "#* updating value '%s'" % v_name
                    update_value(exp_crs, v)

        # Update user lists. We first update the table with the access rights, and
        # then use the updated table to fix the access rights for all tables of the
        # experiment.
        names = {}
        is_group = {}
        modified_access_rights = False
        for a in ['access_add', 'access_change', 'access_revoke']:
            action_node = exp_desc_root.find(a)
            if action_node is not None:
                names.clear()
                is_group.clear()
                if a in ['access_add', 'access_change' ]:
                    for t in ['admin_access', 'input_access', 'query_access' ]:
                        type_node = action_node.find(t)
                        if type_node is not None:
                            for ug in ['user', 'group' ]:
                                for n in type_node.findall(ug):
                                    if ug == 'group':
                                        is_group[n.text] = True
                                    else:
                                        is_group[n.text] = False
                                    if do_debug():
                                        print "DEBUG: %s: %s for %s %s" % (a, t, n.text, ug)
                                    names[n.text] = t
                else:
                    for ug in ['user', 'group' ]:
                        for n in type_node.findall(ug):
                            if ug == 'group':
                                is_group[n.text] = True
                            else:
                                is_group[n.text] = False
                            if do_debug():
                                print "DEBUG: %s for %s %s" % (a, n.text, ug)
                            names[n.text] = 'dummy'

                if a == 'access_revoke' and names.has_key(db_info['user']):
                    print "#* WARNING: current user '%s' can not revoke himself access." % db_info['user']
                    print "   No access is revoked to any user."
                    break
                if a == 'access_change' and names.has_key(db_info['user']) and t != 'admin_access':
                    print "#* WARNING: current user '%s' can not revoke himself access." % db_info['user']
                    print "   No access rights are changed for any user."
                    break

                for n, t in names.iteritems():
                    if a == 'access_add':
                        sqlexe(exp_crs, "SELECT * FROM exp_access where name = '%s'" % n)
                        if exp_crs.rowcount > 0:
                            print "#* WARNING: user '%s' can not be added (already known)." % n
                            continue
                        modified_access_rights = True
                        sqlexe(exp_crs, "INSERT INTO exp_access (name, is_group, acc_type) VALUES (%s, %s, %s)",
                               None, (n, is_group[n], t))
                    elif a == 'access_change':
                        sqlexe(exp_crs, "SELECT * FROM exp_access where name = '%s'" % n)
                        if exp_crs.rowcount == 0:
                            print "#* WARNING: rights for user '%s' can not be changed (user unknown)." % n
                            continue
                        modified_access_rights = True
                        sqlexe(exp_crs, "UPDATE exp_access SET acc_type = %s WHERE name = %s",
                               None, (t, n))
                        sqlexe(exp_crs, "UPDATE exp_access SET is_group = %s WHERE name = %s",
                               None, (is_group[n], n))
                    else:
                        sqlexe(exp_crs, "SELECT * FROM exp_access WHERE name = '%s'" % n)
                        if exp_crs.rowcount == 0:
                            print "#* WARNING: user '%s' can not be removed (user unknown)." % n
                            continue
                        modified_access_rights = True
                        sqlexe(exp_crs, "UPDATE exp_access SET acc_type = 'no_access' WHERE name = %s", None, (n, ))
        if modified_access_rights:
            fix_access_rights(exp_crs, None)

    except SpecificationError, error_msg:
        print "#* ERROR: could not parse value specification for value '%s'" % v_name
        print "   ", error_msg
        exp_db.rollback()
        exp_crs.close()
        exp_db.close()
        sys.exit(1);
    except DatabaseError, error_msg:
        print "#* ERROR: could not add value '%s' to database" % v_name
        print "   ", error_msg
        exp_db.rollback()
        exp_crs.close()
        exp_db.close()
        sys.exit(1);
    except psycopg.Error, error_msg:
        print "#* ERROR: Could not update '%s'." % exp_name
        print "   Reason:", error_msg
        exp_db.rollback()
        exp_crs.close()
        exp_db.close()
        sys.exit(1)
                    
    exp_db.commit()
    exp_crs.close()
    exp_db.close()
    return


def main(argv=None):
    global updt_desc_xml
    
    if argv is None:
        argv = sys.argv[1:]   
    if not parse_cmdline(argv):
        return 

    update_experiment(updt_desc_xml)

    return


if __name__ == "__main__":
    run_mode = getenv("PB_RUNMODE")
    if run_mode == "debug":
        main()
    else:
        try:
            main()
        except SpecificationError, error_msg:
            print "#* ERROR: Invalid experiment update description '%s'" % updt_desc_xml
            print "  ", error_msg
            sys.exit(1)
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
        except xml.parsers.expat.ExpatError, error_msg:
            # XXX Is there no better XML parse exception to catch!?
            print "#* ERROR: XML parse error in experiment description '%s'" % updt_desc_xml
            print "  ", error_msg
            sys.exit(1)
    sys.exit(0)
