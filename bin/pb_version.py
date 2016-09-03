# perfbase - (c) 2004-2006 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de>
#
# pb_version - Print version information
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

from pb_common import print_version
import sys 
import os
import getopt

def print_help():
    """Print the specific help information for this tool."""
    print "perfbase version - Give information on version and copyright"
    print "Usage:"
    print "  perfbase version [options]"
    print "Options:"
    print "--warranty, -w    Information on warranty"
    print "--copying, -c     Information on copying"
    print "--help, -h        This help"

    return

def print_warranty():
    print ""
    print ">>> Warranty Exclusion for perfbase <<<"
    print ""
    print "This is an excerpt of the full license which is provided with the"
    print "perfbase distribution (file COPYING)."
    print """
  11. BECAUSE THE PROGRAM IS LICENSED FREE OF CHARGE, THERE IS NO WARRANTY
FOR THE PROGRAM, TO THE EXTENT PERMITTED BY APPLICABLE LAW.  EXCEPT WHEN
OTHERWISE STATED IN WRITING THE COPYRIGHT HOLDERS AND/OR OTHER PARTIES
PROVIDE THE PROGRAM "AS IS" WITHOUT WARRANTY OF ANY KIND, EITHER EXPRESSED
OR IMPLIED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE.  THE ENTIRE RISK AS
TO THE QUALITY AND PERFORMANCE OF THE PROGRAM IS WITH YOU.  SHOULD THE
PROGRAM PROVE DEFECTIVE, YOU ASSUME THE COST OF ALL NECESSARY SERVICING,
REPAIR OR CORRECTION.

  12. IN NO EVENT UNLESS REQUIRED BY APPLICABLE LAW OR AGREED TO IN WRITING
WILL ANY COPYRIGHT HOLDER, OR ANY OTHER PARTY WHO MAY MODIFY AND/OR
REDISTRIBUTE THE PROGRAM AS PERMITTED ABOVE, BE LIABLE TO YOU FOR DAMAGES,
INCLUDING ANY GENERAL, SPECIAL, INCIDENTAL OR CONSEQUENTIAL DAMAGES ARISING
OUT OF THE USE OR INABILITY TO USE THE PROGRAM (INCLUDING BUT NOT LIMITED
TO LOSS OF DATA OR DATA BEING RENDERED INACCURATE OR LOSSES SUSTAINED BY
YOU OR THIRD PARTIES OR A FAILURE OF THE PROGRAM TO OPERATE WITH ANY OTHER
PROGRAMS), EVEN IF SUCH HOLDER OR OTHER PARTY HAS BEEN ADVISED OF THE
POSSIBILITY OF SUCH DAMAGES.
    """
    return

def print_copying():
    print ""
    print ">>> Copying perfbase <<<"
    print ""
    print "This is an excerpt of the full license which is provided with the"
    print "perfbase distribution (file COPYING)."
    print """
1. You may copy and distribute verbatim copies of the Program's
   source code as you receive it, in any medium, provided that you
   conspicuously and appropriately publish on each copy an appropriate
   copyright notice and disclaimer of warranty; keep intact all the
   notices that refer to this License and to the absence of any warranty;
   and give any other recipients of the Program a copy of this License
   along with the Program.

   You may charge a fee for the physical act of transferring a copy, and
   you may at your option offer warranty protection in exchange for a fee.

2. You may modify your copy or copies of the Program or any portion
   of it, thus forming a work based on the Program, and copy and
   distribute such modifications or work under the terms of Section 1
   above, provided that you also meet all of these conditions:

    a) You must cause the modified files to carry prominent notices
    stating that you changed the files and the date of any change.

    b) You must cause any work that you distribute or publish, that in
    whole or in part contains or is derived from the Program or any
    part thereof, to be licensed as a whole at no charge to all third
    parties under the terms of this License.

    c) If the modified program normally reads commands interactively
    when run, you must cause it, when started running for such
    interactive use in the most ordinary way, to print or display an
    announcement including an appropriate copyright notice and a
    notice that there is no warranty (or else, saying that you provide
    a warranty) and that users may redistribute the program under
    these conditions, and telling the user how to view a copy of this
    License.  (Exception: if the Program itself is interactive but
    does not normally print such an announcement, your work based on
    the Program is not required to print an announcement.)
    """
    return


def main(argv=None):    
    found_arg = False

    if argv is None:
        argv = sys.argv[1:]   
    try:
        options, values = getopt.getopt(argv, 'hwc', ['warranty', 'copying', 'help'])    
    except getopt.GetoptError, error_msg:
        print "#* ERROR: Invalid argument found:", error_msg
        print "   Use option '--help' for a list of valid arguments."
        sys.exit(1)

    for o, v in options:
        if o in ("-h", "--help"):
            print_help()
            found_arg = True
            continue

        if o in ("-w", "--warranty"):
            print_warranty()
            found_arg = True
            continue

        if o in ("-c", "--copying"):
            print_copying()
            found_arg = True
            continue

    if not found_arg:
        print_version()
    return

if __name__ == "__main__":
    main()
    sys.exit(0)

