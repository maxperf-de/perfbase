# perform the tests

test: testing

testing:
	@./runtest

create:
	@./runtest -c

clean:
	@rm -f *~ *.log *.out *.ods

dbclean: clean
	perfbase delete --exp=set_update_TEST --dontask --force

