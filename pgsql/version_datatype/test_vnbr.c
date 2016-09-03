/* test_vnbr.c 

   Test the custom PostgreSQL datatype "version_nbr". To add more
   tests, just add the test cases in the appropiate static arrays
   at the top and increase the N_* number accordingly. 

   (c) 2006 NEC Europe C&C Research Laboratories
    Joachim Worringen <joachim@ccrl-nece.de>

   This file is part of perfbase.

   perfbase is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation; either version 2 of the License, or
   (at your option) any later version.

   perfbase is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License
   along with perfbase; if not, write to the Free Software
   Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

*/

#include "version_nbr.h"

#define N_INVALID 11
char *invalid_vnbr[] = { "", 
			 "5015710751050157107051701015805105801851.1",
			 "1.13a.1", 
			 "1.2.3.4.5.6", 
			 "1.2.3.4.", 
			 "1.2-rc3.0",
			 "1.2 rc3v1",
			 "1.2 rc*3",
			 "1.2 ü3",
			 "1.2 release_canditate3",
			 "rc3"
};

#define N_VALID 7
char   *valid_vnbr[] = { "1", 
			 "1.3.0-rc2",
			 "2.0a",
			 "2.0  ",
			 "2.0  test",
			 "12.3.4.5 beta 2",
			 "1." 
};

#define N_COMPARE 7
char     *cmp_vnbr[] = { "1.2", "1.19",
			 "1.3.0-rc1", "1.3.0-rc2",
			 "2.0.1a", "2.0.1b",
			 "2alpha", "2beta",
			 "1.1.2a", "1.1.2 a",
			 "2.01", "2.1",
			 "1.2.3.4a2", "1.2.3.4a1"
};
/* expected results for         [ eq ne lt le ge gt ] */
bool cmp_result[N_COMPARE][6] = {{0, 1, 1, 1, 0, 0},
				 {0, 1, 1, 1, 0, 0},
				 {0, 1, 1, 1, 0, 0},
				 {0, 1, 1, 1, 0, 0},
				 {1, 0, 0, 1, 1, 0},
				 {1, 0, 0, 1, 1, 0},
				 {0, 1, 0, 0, 1, 1}
};


int main(int argc, char **argv)
{
    version_nbr *v[2];
    int i, j;
    bool b, *bp;

    /* invalid version numbers */    
    v[0] = version_nbr_in(NULL);
    if (v[0] != NULL) {
	printf ("\n#* INVALID: expected NULL return val for NULL input\n");
	return 1;
    }
    printf ("\n");
    for (i = 0; i < N_INVALID; i++) {
	v[0] = version_nbr_in(invalid_vnbr[i]);
	if (v[0] != NULL) {
	    printf ("\n#* INVALID: IN %s, OUT %s (expected NULL return value)\n", 
		    invalid_vnbr[i], version_nbr_out(v[0]));
	    return 1;
	}
	printf ("\n");
    }

    /* valid version numbers */
    for (i = 0; i < N_VALID; i++) {
	v[0] = version_nbr_in(valid_vnbr[i]);
	if (v[0] == NULL) {
	    printf ("\n#* VALID: expected non-NULL return val for input %s\n", valid_vnbr[i]);
	    return 1;
	}
	printf ("VALID: IN: %s, OUT: %s\n", valid_vnbr[i], version_nbr_out(v[0]));	
    }
    
    /* version number comparison */
    bp = &b;
    for (i = 0; i < N_COMPARE; i++) {
	for (j = 0; j < 2; j++) {
	    v[j] = version_nbr_in(cmp_vnbr[2*i+j]);
	    if (v[j] == NULL) {
		printf ("\n#* COMPARE: expected non-NULL return val for input %s\n", cmp_vnbr[2*i+j]);
		return 1;
	    }
	    printf ("CMP: IN: %s, OUT: %s\n", cmp_vnbr[2*i+j], version_nbr_out(v[j]));	
	}
	for (j = 0; j < 6; j++) {
	    switch(j) {
	    case 0:
		bp = version_nbr_eq(v[0], v[1]);
		break;
	    case 1:
		bp = version_nbr_ne(v[0], v[1]);
		break;
	    case 2:
		bp = version_nbr_lt(v[0], v[1]);
		break;
	    case 3:
		bp = version_nbr_le(v[0], v[1]);
		break;
	    case 4:
		bp = version_nbr_ge(v[0], v[1]);
		break;
	    case 5:
		bp = version_nbr_gt(v[0], v[1]);
		break;
	    }
	    if (bp != cmp_result[i][j]) {
		printf ("\n#* COMPARE[%d] %s and %s: expected %d, got %d\n", j, cmp_vnbr[2*i], cmp_vnbr[2*i+1], 
			cmp_result[i][j], bp);
		return 1;
	    }
	}
    }

    printf ("SUCCESS.\n");
    return 0;
}
