# perform the tests

test: testing

testing:
	@./runtest

create:
	@./runtest -c

clean:
	@rm -f *~ *.log *.out *.gp *.eps

dbclean: clean
	perfbase delete --exp=combstrip_TEST --dontask --force
