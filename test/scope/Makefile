# perform the tests

test: testing

testing:
	@./runtest

create:
	@./runtest -c

clean:
	@rm -f *~ *.log scope_*.dat

dbclean: clean
	perfbase delete --exp=scope_TEST --dontask --force

