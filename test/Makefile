# run the perfbase test suite

TESTDIRS=fixed runs derived eval plain_table plottype sweep update \
	errors count filename map marker missing boolean regexp \
	input oponesrc optwosrc distrib quote exist default \
	order pset split attach filter slice runindex combiner \
	lines limit combiner2 plot3d xml multi_target map2 regexp2 \
	scope sweep_group opendoc set_update combstrip frequency \
	normalize

test: 
	@./runtest

testing:
	@echo "* Running the perfbase test suite:"
	@echo
	@for dir in $(TESTDIRS) ; do \
	  (cd $$dir; make test; echo ) ; \
	done
	@echo "* Done."

testing_all: testing
	@echo "* Running additional 'access' test (requires unsafe database configuration)"
	@echo
	(cd access; make test; echo ) 
	@echo "* Running additional 'version' test (requires custom SQL datatype)"
	@echo
	(cd version; make test; echo ) 
	@echo "* Done completely."

create:
	@echo "* Re-creating verification data for perfbase test suite:"
	@echo
	@for dir in $(TESTDIRS) ; do \
	  (cd $$dir; make create; echo ) ; \
	done
	@echo "* Done."

create_all: create
	@echo "* Running additional 'access' test (requires unsafe database configuration)"
	@echo
	(cd access; make create; echo ) 
	@echo "* Running additional 'version' test (requires custom SQL datatype)"
	@echo
	(cd version; make create; echo ) 
	@echo "* Done completely."

clean:
	rm -f test.log
	@for dir in $(TESTDIRS) access version ; do \
	  (cd $$dir; make clean; echo ) ; \
	done

dbclean: clean
	@for dir in $(TESTDIRS) access version ; do \
	  (cd $$dir; make dbclean; echo ) ; \
	done

distclean: dbclean
	rm -f runtest

