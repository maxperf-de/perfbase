# perform the tests

test: testing

testing:
	@./runtest

create:
	@./runtest -c

demo:
	@./runtest -k

clean:
	@rm -f *~ *.log *.out *.gp *.eps

dbclean: clean
	perfbase delete --exp=sweep_group_TEST --dontask --force

