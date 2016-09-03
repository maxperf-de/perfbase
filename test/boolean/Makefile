# perform the tests

test: testing

testing:
	@./runtest

create:
	@./runtest -c

clean:
	@rm -f *~ *.log *.out

dbclean: clean
	perfbase delete --exp=boolean_TEST --dontask --force

