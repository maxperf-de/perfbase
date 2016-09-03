# perfbase - (c) 2004-2005 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de>
#
# pb_attach - Store and retrieve perfbase XML files (queries, input descriptions, ...) 
#             to the experiment.
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

from string import lower, strip, upper
import getopt
import xml
import sys
from sys import exit, argv
from os import F_OK, R_OK, getenv, access
from xml.etree import ElementTree

# DBAPI implementation to access PostgreSQL
import psycopg2 as psycopg

# global variables
db_info = { 'host':None, 'port':None, 'name':None, 'user':None, 'password':None } 
exp_name = None
xml_filename = None
xml_synopsis = None
xml_description = None
xml_name = None
do_force= False
confirm_delete = True
interactive = False

def print_help():
    """Print the specific help information for this tool."""
    print "perfbase attach - Attach (XML) files to a perfbase experiment"
    print "Synopsis:"
    print "  perfbase attach [--exp=<exp>] [--name=<name>] [--synopsis=<text>] [--attach=<file>] --xml=file"
    print "Arguments:"
    print "--exp=<exp>, -e <exp>          Use experiment <exp>"
    print "--name=<name>, -n <name>       Name to reference the file"
    print "--xml=<file>, -x <file>        XML file to be stored ('-' for stdout)"
    print "--synopsis=<text>, -s <text>   Brief one-line description"
    print "--desc=<text>, -d <text>       More elaborate description (any length)"
    print "--put, -p                      Attach the file to the experiment"
    print "--get, -g                      Dump an attachement from an experiment to a file"
    print "--list, -l                     List all available attachments."
    print "--force                        Force replacement of existing attachment."
    print "--delete                       Delete an attachment from the experiment."
    print "--dontask                      Do not request confirmation for deletion ."
    print "--interactive, -i              Enter name, synopsis and description interactively (not from XML)."
    print_generic_dbargs()
    return
    

def parse_cmdline(argv):
    """Set default values for externally controled parameters, and set them according to parameters."""
    global xml_filename, xml_synopsis, xml_description, xml_name, interactive
    global exp_name, do_force
    global db_info
  
    argv2 = argv_preprocess(argv)
    n_params = param_count(argv2)
    action = None

    # parse arguments
    try:
        options, values = getopt.getopt(argv2, 'hVve:n:x:s:d:pgil', ['dbhost=', 'dbport=', 'dbuser=', 'dbpasswd=',
                                                                     'help', 'version', 'verbose', 'exp=', 
                                                                     'name=', 'xml=', 'synopsis=', 'desc=',
                                                                     'put', 'get','delete', 'list', 'force',
                                                                     'dontask', 'interactive', 'sqltrace' ])
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
            sys.exit()
            continue
        if o in ("--version", "-V"):
            print_version()
            sys.exit()
            continue
        if o == "--sqltrace":
            set_sql_trace(True)
            continue

        if o in ("-e", "--exp"):
            exp_name = v
            continue
        if o in ("-d", "--desc"):
            xml_description = v
            continue
        if o in ("-s", "--synopsis"):
            xml_synopsis = v
            continue
        if o in ("-x", "--xml"):
            xml_filename = v
            continue
        if o in ("-n", "--name"):
            xml_name = v
            continue
        if o in ("-p", "--put"):
            if action is None:
                action = "put"
            else:
                raise SpecificationError, "action has to be specified exactly once."
            continue
        if o in ("-g", "--get"):
            if action is None:
                action = "get"
            else:
                raise SpecificationError, "action has to be specified exactly once."
            continue
        if o == "--delete":
            if action is None:
                action = "delete"
            else:
                raise SpecificationError, "action has to be specified exactly once."
            continue
        if o in ("-l", "--list"):
            if action is None:
                action = "list"
            else:
                raise SpecificationError, "action has to be specified exactly once."
            continue
        if o == "--force":
            do_force = True
            continue
        if o == "--dontask":
            confirm_delete = False
            continue
        if o in ("-i", "--interactive"):
            interactive = True
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

    if exp_name is None:
        if xml_filename is not None and action == "put":
            get_xml_info(xml_filename)
    if exp_name is None:
        exp_name = getenv("PB_EXPERIMENT")
    if exp_name is None:
        raise SpecificationError, "experiment name not specified (use option --exp=...)"

    # validate arguments
    if action is None:
        raise SpecificationError, "no action specified (specify '--put', '--get' or '--delete')"
    if xml_filename is None and action == "put":        
        raise SpecificationError, "no filename specified (use option '--xml=...')"
    if xml_filename is None and action == "get":
        xml_filename = "-"
    if action == "put" and xml_filename == '-':
        raise SpecificationError, "action 'put' does not support input from stdin."
    if action in ("delete", "get") and xml_name is None:
        raise SpecificationError, "action '%s' requires specification of attachment name (use option --name=...)." % action
        
    return action


def get_xml_info(fname):
    """Check the content of the XML file and get missing information from it."""
    global xml_synopsis, xml_description, xml_name, interactive
    global exp_name

    if be_verbose():
        print "#* Parsing XML file ", fname

    if access(fname, F_OK|R_OK) == False:
        raise SpecificationError, "can not access input file %s" % fname

    filetype = "unknown"
    try:
        xml_tree = ElementTree.parse(fname)
        xml_root = xml_tree.getroot()
    except xml.parsers.expat.ExpatError, error_msg:
        # this file is not necessarily an XML file!
        raise SpecificationError, "file '%s' is not a valid XML file." % fname

    if xml_root and xml_root.tag in ("query", "input", "experiment", "experiment_update"):
        filetype = xml_root.tag

        # get missing information from the XML file
        if not exp_name:
            exp_name = xml_root.findtext('experiment')
            if not exp_name:
                raise SpecificationError, "no experiment specified (option '--exp')"
            if be_verbose():
                print "#* accessing experiment '%s'" % exp_name

        if not xml_name:
            if not interactive:
                xml_name = xml_root.get('id')
            else:
                xml_name = read_from_stdin("Name of the %s description:" % filetype)
            if not xml_name:
                raise SpecificationError, "name for storing this file was not specified (option '--name)"

        if not xml_synopsis or xml_synopsis == '-':
            if not interactive and xml_synopsis != '-':
                xml_synopsis = xml_root.findtext('synopsis')
            else:
                xml_synopsis = read_from_stdin("Synopsis of this %s description:" % filetype)
        if not xml_synopsis:
            print "#* WARNING: no synopsis specified - use option '--synopsis'."

        if not xml_description or xml_description == '-':
            if not interactive and xml_description != '-':
                xml_description = xml_root.findtext('description')
            else:
                xml_description = read_from_stdin("Description for this %s description:" % filetype)
    else:
        raise SpecificationError, "file '%s' is not a perfbase XML file." % fname

    return filetype


def store_file(crs, fname):
    """Load the file into memory, and store it in the database together with the related
    metadata. We do not use BLOBs here as this functionality is designed for XML files."""
    global xml_filename, xml_synopsis, xml_description, xml_name
    global db_info

    filetype = get_xml_info(xml_filename)

    data_fd = open(fname, 'r')
    file_data = ""
    for l in data_fd.readlines():
        file_data += l
    data_fd.close()          

    sqlexe(crs, "SELECT creator FROM xml_files WHERE name = %s", None, (xml_name,))
    if crs.rowcount == 0:
        sqlexe(crs, "INSERT INTO xml_files (creator,created,filename,name,type,synopsis,description,xml) \
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", None,
               (db_info['user'], mk_timestamp(), xml_filename, xml_name,
                filetype, xml_synopsis, xml_description, file_data))
    elif do_force:
        sqlexe(crs, "UPDATE xml_files SET creator=%s,created=%s,filename=%s,type=%s,synopsis=%s,\
        description=%s,xml=%s WHERE name=%s", None,
               (db_info['user'], mk_timestamp(), xml_filename, 
                filetype, xml_synopsis, xml_description, file_data, xml_name))
    else:
        raise SpecificationError, "attachment '%s' does already exist. (use '--force' to overwrite)" % xml_name        
        
    return


def dump_file(crs, fname):
    """Dump data from the database to a file in the filesytem.
    We do not use BLOBs here as this functionality is designed for XML files."""
    global xml_name, exp_name
        
    if fname != '-':
        data_fd = open(fname, 'w')
    else:
        data_fd = sys.stdout

    if not dump_attachment (crs, xml_name, data_fd):
        raise SpecificationError, "attachment '%s' not found in experiment '%s'." % (xml_name, exp_name)

    if fname != '-':
        data_fd.close()          

    return


def delete_file(crs):
    global confirm_delete
    global exp_name, xml_name
    
    sqlexe(crs, "SELECT name FROM xml_files WHERE name = %s", None, (xml_name,))
    if crs.rowcount == 0:
        if be_verbose():
            print "#* WARNING: attachment '%s' does not exist in experiment '%s'." % (xml_name, exp_name)
        sys.exit(1)

    if confirm_delete:
        print "*** ALL RELATED FILE DATA WILL BE LOST WHEN DELETING AN ATTACHMENT:"
        print "    Really delete attachment '%s' from experiment '%s'? <yes/NO>" % (xml_name, exp_name)
        if strip(upper(sys.stdin.readline())) != "YES":
            print "NOT deleting anything from experiment '%s'. Exiting." % exp_name
            return
        
    sqlexe(crs, "DELETE FROM xml_files WHERE name = %s", None, (xml_name, ))
                 
    return


def list_attachments(crs):
    """List all attachments in the experiment."""
    for xml_type in ("query", "input", "experiment", "experiment_update"):
        if xml_name is None:
            sqlexe(crs, "SELECT type,name,synopsis,description,creator,created FROM xml_files WHERE type = %s",
                        None, (xml_type, ))
        else:
            sqlexe(crs, "SELECT type,name,synopsis,description,creator,created FROM xml_files WHERE name = %s",
                   None, (xml_name, ))
        if crs.rowcount > 0:
            nim = build_name_idx_map(crs)
            if not be_verbose() and xml_name is None:
                print "# %-20s %-8s %s" % ("name", "type", "synopsis")
            for row in crs.fetchall():
                if be_verbose() or xml_name is not None:
                    print "'%s' (%s description)" % (row[nim['name']], row[nim['type']])
                    print "    Synopsis   : %s" % (row[nim['synopsis']])
                    print "    From       : %s, %s" % (row[nim['creator']], row[nim['created']])
                    
                    desc = row[nim['description']]
                    if desc and len(desc) > 0:
                        print "    Description:"
                        print_formatted(desc, 4, 60)
                else:
                    print "%-22s %-8s %s" % (row[nim['name']], row[nim['type']], row[nim['synopsis']])

        if xml_name is not None:
            break
    return


def main(argv=None):
    global xml_filename, xml_synopsis, xml_description, xml_name
    global exp_name, db_info
    
    if argv is None:
        argv = sys.argv[1:]   
    action = parse_cmdline(argv)

    # Determine the database server to be used. Preference of the parameters:
    # cmdline > from xml file  > environment >
    db_info["name"] = "pb_"+exp_name.lower()
    get_dbserver(None, db_info)
    exp_db = open_db(db_info, False, exp_name)
    if exp_db is None:
        sys.exit(1)
    crs = exp_db.cursor()

    if action == "put":
        store_file(crs, xml_filename)
    elif action == "get":
        dump_file(crs, xml_filename)
    elif action == "delete":
        delete_file(crs)
    elif action == "list":
        list_attachments(crs)

    crs.close()
    exp_db.commit()
    exp_db.close()
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
            print "#* User aborted operation."
            sys.exit(0)
        except psycopg.ProgrammingError, error_msg:
            if error_msg.args[0].find('permission denied') > 0:
                if exp_name != 'perfbase':
                    print "#* ERROR: user '%s' has insufficient privileges to access experiment '%s'" \
                          % (db_info['user'], exp_name)
                else:
                    print "#* ERROR: user '%s' has insufficient privileges to access perfbase database server" \
                          % (db_info['user'])
            else:
                print "#*", error_msg
            sys.exit(1)
        except SpecificationError, error_msg:
            print "#* ERROR: Abort by exception:"
            print "  ", error_msg
            sys.exit(1)
        except StandardError, error_msg:
            print "#* ERROR: Abort by exception:"
            print "  ", error_msg
            sys.exit(1)

    sys.exit(0)
