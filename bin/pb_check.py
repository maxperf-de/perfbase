# perfbase - (c) 2004-2006 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de>
#
# pb_check - Check & fix, and update, perfbase experiment databases
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

from os import F_OK, R_OK, getenv, access
from os.path import basename, dirname
from datetime import datetime
from string import strip, upper
from random import randint

import getopt
import sys

# DBAPI implementation to access PostgreSQL
import psycopg2 as psycopg
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# globals
db_info = { 'host':None, 'port':None, 'name':None, 'user':None, 'password':None } 
do_update = False
do_clean = False
do_tune = False
test_only = True
index_values = []
exp_names = []
all_exp = False

def print_help():
    """Print the specific help information for this tool."""
    print "perfbase check - Check & report, clean, fix, and update, perfbase experiment databases"
    print "Arguments:"
    print "--all, -a                   Check all available and accessible experiments"
    print "--exp=<exp[,...]>, -e <exp[,...]> "
    print "                            Check the database of experiment(s) <exp[,...]>"
    print "--fix, -f                   Actually fix all detected issues."
    print "--update, -u                Update the database(s) to the current version of perfbase"
    print "--tune, -t                  improve general database performance"
    print "--index=<value,...>, -i <value,...>"
    print "                            Create index for <value>(s) to speed up queries that filter for it."
    print "--clean, -c                 Clean up the database (delete inactive runs)"
    print_generic_dbargs()


def update_0_to_1(db):
    """Update todo:
    0 -> 1: - add column 'version integer' to exp_metadata tables of the experiment."""

    # First update the experiment itself, then the experiment meta table.
    if be_verbose():
        print "#* updating from version 0 to 1"

    crs = db.cursor()

    sqlexe(crs, "ALTER TABLE exp_metadata ADD COLUMN version integer", "#* adding version column:")
    sqlexe(crs, "UPDATE exp_metadata SET version = 1", "#* set version to 1:")

    crs.close()
    db.commit()
    
    return True


def update_1_to_2(db):
    """Update todo:
    1 -> 2: - create table 'exp_access' and give the current user admin rights.
            - set access rights to all tables accordingly"""               
    global db_info

    if be_verbose():
        print "#* updating from version 1 to 2."

    crs = db.cursor()
    try:
        # create access right table and install current user as admin
        sqlexe(crs, "CREATE TABLE exp_access ( name varchar(256), is_group boolean, acc_type varchar(32))")
        sqlexe(crs, "INSERT INTO exp_access (name, is_group, acc_type) VALUES (%s, %s, %s)",
               None, (db_info['user'], False, 'admin_access'))

        # set access rights to all tables - only a single admin user after this!
        names_cmd = { db_info['user'] : 'GRANT', 'PUBLIC' : 'REVOKE' }
        tables = ['exp_metadata', 'run_metadata', 'exp_values', 'exp_access', 'rundata_once']
        sqlexe(crs, "SELECT index FROM run_metadata")
        for db_row in crs.fetchall():
            tables.append("rundata_"+str(db_row[0]))    
        for t in tables:
            for n, cmd in names_cmd.iteritems():
                table_access_rights(crs, n, False, t, cmd, 'ALL')

        # update version number 
        sqlexe(crs, "UPDATE exp_metadata SET version = 2", "#* set version to 2:")
    except psycopg.Error, error_msg:
        print error_msg
        print "#* ERROR: Could not update from version 1 to 2." 
        crs.close()
        db.close()
        sys.exit(1)

    crs.close()
    db.commit()    

    return True


def update_2_to_3(db):
    """Update todo:
    2 -> 3: - create table 'param_sets' and set access rights accordingly
            - create a column in this table for all only-once parameters 
    """               
    if be_verbose():
        print "#* updating from version 2 to 3."

    crs = db.cursor()
    try:
        sqlexe(crs, "CREATE TABLE param_sets ( set_name varchar(256) UNIQUE )")
        sqlexe(crs, "SELECT name,sql_type FROM exp_values WHERE is_result = 'f' AND only_once = 't'")
        if crs.rowcount > 0:
            for row in crs.fetchall():
                sqlexe(crs, "ALTER TABLE param_sets ADD COLUMN %s %s" % (row[0],row[1]))
                
        fix_access_rights(crs, None, 3)
        
        # update version number 
        sqlexe(crs, "UPDATE exp_metadata SET version = 3", "#* set version to 3:")
    except psycopg.Error, error_msg:
        print error_msg
        print "#* ERROR: Could not update '%s' from version 2 to 3."
        crs.close()
        db.close()
        sys.exit(1)

    crs.close()
    db.commit()    

    return True

def update_3_to_4(db):
    """Update todo:
    3 -> 4: - create table 'xml_files' and set access rights accordingly
    """               
    if be_verbose():
        print "#* updating from version 3 to 4."

    crs = db.cursor()
    try:
        sqlexe(crs, """CREATE TABLE xml_files (
        creator varchar(256),
        created timestamp,
        filename varchar(256),
        name varchar(64) UNIQUE,
        type varchar(16),
        synopsis varchar(256),
        description text,
        xml text
        )""")

        fix_access_rights(crs, None, 4)
        
        # update version number 
        sqlexe(crs, "UPDATE exp_metadata SET version = 4", "#* set version to 4:")
    except psycopg.Error, error_msg:
        print error_msg
        print "#* ERROR: Could not update from version 3 to 4."
        crs.close()
        db.close()
        sys.exit(1)

    crs.close()
    db.commit()    

    return True

def update_4_to_5(db):
    """Update todo:
    4 -> 5: - transform all rundata_* table into a single 'rundata' table
    """               

    if be_verbose():
        print "#* updating from version 4 to 5. Please be patient, this can take time."

    crs = db.cursor()
    try:
        # create rundata table
        runtable_str = "pb_run_index integer,"
        value_names = []
        value_info = {}
        
        sqlexe(crs, "SELECT * FROM exp_values WHERE only_once='false'")
        v_nim = build_name_idx_map(crs)
        for db_row in crs.fetchall():
            runtable_str += " %s %s" % (db_row[v_nim['name']], db_row[v_nim['sql_type']])
            value_names.append(db_row[v_nim['name']])
            value_info[db_row[v_nim['name']]] = db_row

            v_dflt = db_row[v_nim['default_content']]
            if v_dflt is not None and len(v_dflt) > 0:
                # This value has a default content.
                runtable_str += " DEFAULT %s," % mk_sql_const(db_row[v_nim['sql_type']], v_dflt)
            elif v_dflt is None:
                # All values without default content have a non-null constraint. An
                # empty string (len() == 0) indicates that a default content of NULL
                # is valid => no non-NULL constraint in this case!
                runtable_str += " NOT NULL,"
            else:
                runtable_str += ","

        # remove the traling ','
        runtable_str = runtable_str[:-1]

        sqlexe(crs, "CREATE TABLE rundata (%s)" % (runtable_str))

        # transfer data from all rundata_* tables to the new single table
        sqlexe(crs, "SELECT index FROM run_metadata")
        for meta_row in crs.fetchall():
            idx = meta_row[0]
            if be_verbose():
                print "%d" % idx,
                sys.stdout.flush()
            
            sqlexe(crs, "SELECT * FROM rundata_%d" % idx)
            nim = build_name_idx_map(crs)
            for data_row in crs.fetchall():
                insert_str = "pb_run_index,"
                data_str = "%d," % idx
                for v in value_names:
                    if data_row[nim[v.lower()]] is not None:
                        data_str += "%s," % quote_value(value_info[v], v_nim, data_row[nim[v.lower()]])
                        insert_str += "%s," % v
                data_str = data_str[:-1]
                insert_str = insert_str[:-1]
                
                sqlexe(crs, "INSERT INTO rundata ( %s ) VALUES ( %s )" % (insert_str, data_str),
                       "#* DEBUG: inserting data with")

            # delete this rundata_* tables
            sqlexe(crs, "DROP TABLE rundata_%d" % idx)
        print ""

        fix_access_rights(crs, None, 5)
      
        # update version number 
        sqlexe(crs, "UPDATE exp_metadata SET version = 5", "#* set version to 5:")
    except psycopg.Error, error_msg:
        print error_msg
        print "#* ERROR: Could not update from version 4 to 5."
        crs.close()
        db.close()
        sys.exit(1)

    crs.close()
    db.commit()    

    return True

def update_experiment(db, db_name):
    """Update the tables of an experiment to match the current version.
    Version 0: 'no version' (no version management introduced).
    Version 1: first release with version control-
    Version 2: multi-user capability.
    Version 3: support for named parameter sets.
    Version 4: XML file attachments.
    Version 5: cleaner database layout."""    
    global test_only

    if be_verbose():
        print "#* updating experiment database '%s'" % db_name

    crs = db.cursor()

    sqlexe(crs, "SELECT * FROM exp_metadata" )
    if crs.rowcount == 0:
        raise DatabaseError, "corrupted experiment: no metadata stored. Wrong experiment name (case is relevant!)"
    if crs.rowcount > 1:
        raise DatabaseError, "corrupted experiment: more than one set of metadata stored."
    nim = build_name_idx_map(crs)

    db_version = 0
    if nim.has_key('version'):
        db_row = crs.fetchone()
        db_version = db_row[nim['version']]

    if db_version == pb_db_version:
        print "#* Experiment is up to date."
        return
    if db_version > pb_db_version:
        print "#* ERROR: version '%d' of experiment is more recent than version '%d' of perfbase tools." \
              % (db_version, pb_db_version)
        print "          You need to update the perfbase tools!"
        sys.exit(1)

    # start updating
    while db_version < pb_db_version:
        cmd = "update_%d_to_%d(db)" % (db_version, db_version+1)
        if not test_only and not eval(cmd):
            print "#* ERROR: update from version %d to %d failed!" % (db_version, db_version+1)
            sys.exit(1)
        db_version += 1

    crs.close()
    return


def clean_experiment(db, db_name):
    """Clean up the experiment database. First of all, this means removing inactive
    runs permanently."""
    if be_verbose():
        print "#* cleaning experiment database '%s'" % db_name

    crs = db.cursor()
    sqlexe(crs, "SELECT index FROM run_metadata WHERE active = false")

    inactive_ids = crs.fetchall()
    if len(inactive_ids) == 0:
        print "#* Found no inactive runs - nothing to clean."
        return
    
    for row in inactive_ids:
        if be_verbose():
            print "   removing inactive run %d" % row[0]
        sqlexe(crs, "DELETE FROM run_metadata WHERE index = %s", None, (row[0], ))
        sqlexe(crs, "DELETE FROM rundata WHERE pb_run_index = %s", None, (row[0], ))

    crs.close()
    db.commit()
    return


def tune_experiment(db, db_name):
    """Create indices to speed up operation."""
    if be_verbose():
        print "#* tuning experiment database '%s'" % db_name

    crs = db.cursor()
    try:
        sqlexe(crs, "CREATE INDEX idx_id_rundata ON rundata(pb_run_index)")
    except psycopg.ProgrammingError, error_msg:
        pass
    
    crs.close()
    db.commit()
    return


def create_index(db, db_name, value):
    """Create indices to speed up operation."""
    if be_verbose():
        print "#* creating index for '%s' in database '%s'" % (value, db_name) 

    crs = db.cursor()

    sqlexe(crs, "SELECT only_once FROM exp_values WHERE name='%s'" % value)
    if crs.rowcount == 0:
        print "#* ERROR: value '%s' does not exist." % value
        return 0
    if crs.fetchone()[0]:
        print "#* ERROR: value '%s' is an 'only-once' value. " % value
        print "   An index can only be created for values with multiple occurence."
        return 0

    try:
        sqlexe(crs, "CREATE INDEX idx_%s_rundata ON rundata(%s)" % (value.lower(), value.lower()))
    except psycopg.ProgrammingError, error_msg:
        raise DatabaseError, "creating index for '%s' failed" % value
    
    crs.close()
    db.commit()
    return 1


def fix_experiment(db, db_name):
    """Fix & clean up an experiment database."""
    global test_only

    if be_verbose():
        print "#* checking experiment database '%s'" % db_name

    # Remove all dangling query tables. Need to lock database for this to avoid
    # removing query tables that are in use!
    if be_verbose():
        print "   ...for dangling query tables"
    crs = db.cursor()
    sqlexe(crs, "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename~'^qt_'")
    if test_only and be_verbose() and crs.rowcount > 0:
        print "#* Found %d temporary query tables." % crs.rowcount
        
    if not test_only and crs.rowcount > 0:
        print "#* Found %d temporary query tables - delete them? (yes/NO)" % crs.rowcount
        print "   MAKE SURE THAT NO QUERY IS CURRENTLY ONGOING!"
        if strip(upper(sys.stdin.readline())) != "YES":
            print "   No table was deleted."
        else:
            for row in crs.fetchall():
                if be_verbose():
                    print "   removing table '%s'" % row[0]
                sqlexe(crs, "DROP TABLE %s" % row[0])
            db.commit()

    # Check if all values (from 'exp_values') are actually contained either in the 'rundata_once'
    # table or the 'rundata_N' tables. Inconsistencies in this area can occur due to interrupted
    # update operations.
    # First, find a valid run index to speed up the check below.
    if be_verbose():
        print "   ...for values consistency"
    idx_cond = ""
    sqlexe(crs, "SELECT index FROM run_metadata WHERE active")
    if crs.rowcount > 0:
        idx_cond = "WHERE pb_run_index=%d" % crs.fetchone()[0]   

    sqlexe(crs, "SELECT * FROM exp_values")
    nim = build_name_idx_map(crs)
    all_valuerows = crs.fetchall()
    for vrow in all_valuerows:
        vname = vrow[nim['name']]
        inconsistent_value = False

        if vrow[nim['only_once']]:
            try:
                sqlexe(crs, "SELECT %s FROM rundata_once" % vname)
            except psycopg.ProgrammingError, error_msg:
                # not found!
                if test_only:
                    print "#* Value '%s' defined as only once, but not found in data table"  % vname
                else:
                    print "#* Value '%s' defined as only once, but not found in data table  - DELETE IT? (yes/NO)" \
                          % vname
                    inconsistent_value = True
        else:
            # multiple - check, if value is found in the data table.
            try:
                sqlexe(crs, "SELECT %s FROM rundata %s" % (vname, idx_cond))
            except psycopg.ProgrammingError, error_msg:
                # not found!
                if test_only:                    
                    print "#* Value '%s' defined as multiple, but not found in data table" % vname
                else:
                    print "#* Value '%s' defined as multiple, but not found in data table  - DELETE IT? (yes/NO)" \
                          % vname
                    inconsistent_value = True
        if inconsistent_value:
            crs.close()
            db.commit()
            crs = db.cursor()
            if strip(upper(sys.stdin.readline())) != "YES":
                print "   No value was deleted."
            else:
                if be_verbose():
                    print "   removing value '%s'" % vname
                sqlexe(crs, "DELETE FROM exp_values WHERE name='%s'" % vname)
                db.commit()

    # When transfering databases (via dump/restore), it happened (always happens?) that the index counters
    # were not restored in the original state. Thus, they delivered index values which are already in use,
    # which makes im impossible to add new data to the experiment.
    # To test this, we need to insert a dummy entry in the run_metadata table and see if the generated index
    # value does not yet exist in the rundata_once or rundata table (to be more precise: that the new index 
    # is larger than all existing run indexes). Fixing is done by repeated insertion and removal of dummy runs.
    if be_verbose():
        print "   ...for index consistency"
    run_key = randint(0,1000000000)
    tstamp  = mk_timestamp()
    sqlexe(crs, "INSERT INTO run_metadata (key, created) VALUES (%s, %s)", None, (run_key, tstamp));
    sqlexe(crs, "SELECT index FROM run_metadata WHERE (created = '%s' AND key = '%s')" % (tstamp, run_key))
    run_idx = crs.fetchone()[0]
    # remove the dummy row
    sqlexe(crs, "DELETE FROM run_metadata WHERE key = %s AND created = %s", None, (run_key, tstamp));
    
    sqlexe(crs, "SELECT max(run_index) FROM rundata_once WHERE run_index >= %s", None, (run_idx, ))
    max_idx = crs.fetchone()[0]
    if max_idx is not None:
        diff = max_idx - run_idx + 1
        if be_verbose():
            print "   Bumping run index from %d to %d" % (run_idx, max_idx+1)
        if not test_only:
            while diff > 0:
                # insert and remove as many dummy rows as necessary to bump the index beyond the current max index
                sqlexe(crs, "INSERT INTO run_metadata (key, created) VALUES (%s, %s)", None, (run_key, tstamp));
                sqlexe(crs, "DELETE FROM run_metadata WHERE key = %s AND created = %s", None, (run_key, tstamp));
                diff -= 1
            db.commit()
        
    # Check for stray runs, which are runs with an index that is not contained in
    # the metadata table. It is unclear how this can happen, but it occured.
    # Such runs have to be deleted.
    if be_verbose():
        print "   ...for run consistency"
    sqlexe(crs, "SELECT index FROM run_metadata", None, None)
    known_runs = crs.fetchall()
    sqlexe(crs, "SELECT run_index FROM rundata_once", None, None)
    purge_runs = []
    for once_idx in crs.fetchall():
        if not once_idx in known_runs:
            purge_runs.append(once_idx[0])

    for idx in purge_runs:
        if be_verbose():
            print "      Purging stray run %d" % (idx)
        if not test_only:
            sqlexe(crs, "DELETE FROM rundata_once WHERE run_index = %s" % idx)
            sqlexe(crs, "DELETE FROM rundata WHERE pb_run_index = %s" % idx)

    if not test_only:
        db.commit()
    
    crs.close()
    return


def vacuum_experiment(db, db_name):
    if be_verbose():
        print "#* Now performing a vacuum on the database."

    # can not vacuum database inside a transaction
    db.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    crs = db.cursor()
    try:
        sqlexe(crs, "VACUUM FULL")
    except psycopg.Error, error_message:
        print error_message
        sys.exit(1)
    
    crs.close()
    return


def parse_cmdline(argv):
    """Set default values for externally controled parameters, and set them according to parameters."""
    global exp_names, all_exp, do_update, do_fix, do_clean, test_only, do_tune
    global index_values
    global db_info
  
    # parse arguments
    try:
        options, values = getopt.getopt(argv, 'hVve:afucti:', ['dbhost=', 'dbport=', 'dbuser=', 'dbpasswd=',
                                                               'help', 'version', 'verbose', 'all', 'exp=',
                                                               'fix', 'update', 'debug', 'clean', 'sqltrace',
                                                               'tune', 'index='])
    except getopt.GetoptError, error_msg:
        print "#* ERROR: Invalid argument found:", error_msg
        print "   Use option '--help' for a list of valid arguments."
        sys.exit(1)

    for o, v in options:
        if o in ("-v", "--verbose"):
            set_verbose(True)
            continue
        if o == "--debug":
            set_debug(True)
            continue
        if o == "--sqltrace":
            set_sql_trace(True)
            continue
        if o in ("-h", "--help"):
            print_help()
            sys.exit()
            continue
        if o in ("--version", "-V"):
            print_version()
            sys.exit()
            continue

        if o in ("-e", "--exp"):
            if not all_exp:
                exp_names.extend(v.split(','))
            else:
                print "#* ERROR: specifiy either --exp= or --all"
                sys.exit(1)
            continue
        if o in ("-f", "--fix"):
            test_only = False
            continue
        if o in ("-c", "--clean"):
            do_clean = True
            continue
        if o in ("-t", "--tune"):
            do_tune = True
            continue
        if o in ("-i", "--index"):
            index_values.extend(split(v,','))
            continue
        if o in ("-u", "--update"):
            do_update = True
            test_only = False
            continue
        if o in ("-a", "--all"):
            if len(exp_names) == 0:
                all_exp = True
            else:
                print "#* ERROR: specifiy either --exp= or --all"
                sys.exit(1)
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

    if len(exp_names) == 0 and not all_exp:
        e = getenv("PB_EXPERIMENT")
        if not e:
            print "#* ERROR: no experiment specified"
            print_help()
            sys.exit(1)
        exp_names = [e]
        
    return


def main(argv=None):
    global db_info, do_update, do_clean, index_values
    
    if argv is None:
        argv = sys.argv[1:]
    parse_cmdline(argv)

    # Determine the database server to be used. Preference of the parameters:
    # cmdline > environment > default
    get_dbserver(None, db_info)

    if all_exp:
        check_dbs = find_all_experiments(db_info)
    else:
        check_dbs = {}
        for e in exp_names:
            db_info['name'] = get_dbname(e)
            check_dbs[db_info['name']] = open_db(db_info, False, e)

    for db_name,db in check_dbs.iteritems():
        if not do_update and not check_db_version(db):
            raise DatabaseError, "version mismatch of experiment database and commandline tools"

        if do_update:
            update_experiment(db, db_name)
        if do_clean:
            clean_experiment(db, db_name)

        fix_experiment(db, db_name)

        if do_tune:
            tune_experiment(db, db_name)

        idx_cnt = 0
        if len(index_values) > 0:
            for v in index_values:
                idx_cnt += create_index(db, db_name, v)
            
        if not test_only or do_tune or do_update or do_clean or \
               (len(index_values) == idx_cnt and idx_cnt > 0):
            vacuum_experiment(db, db_name)
            
        db.close()

    return


if __name__ == "__main__":
    run_mode = getenv("PB_RUNMODE")
    if run_mode == "debug":
        main()
    else:
        try:
            main()
        except psycopg.ProgrammingError, error_msg:
            if error_msg.args[0].find('permission denied') > 0:
                print "#* ERROR: user '%s' has insufficient privileges to access experiment" \
                      % (db_info['user'])
            else:
                print "#*", error_msg
            sys.exit(1)
        except KeyboardInterrupt:
            print ""
            print "#* User aborted input operation. No data written to database."
            sys.exit(1)
        except DatabaseError, error_msg:
            print "#* ERROR: Something is wrong with the database. No data written to database."
            print "  ", error_msg
            sys.exit(1)
        except StandardError, error_msg:
            print "#* ERROR: Abort by exception:"
            print "  ", error_msg
            sys.exit(1)
    sys.exit(0)
