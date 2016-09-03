# perform the tests

test: testing

testing:
	@./runtest

create:
	@./runtest -c

clean:
	@rm -f *~ *.log *.out *.ods
	@rm -rf opendoc_?.test opendoc_?.vfy

dbclean: clean
	perfbase delete --exp=opendoc_TEST --dontask --force

