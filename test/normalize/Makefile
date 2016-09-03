# perform the tests

test: testing

testing:
	@./runtest

create:
	@./runtest -c

clean:
	@rm -f *~ *.log *.out *.gp *.eps

dbclean: clean
	perfbase delete --exp=normalize_TEST --dontask --force
