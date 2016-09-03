# perform the tests

test: testing

testing:
	@./runtest

create:
	@./runtest -c

clean:
	@rm -f *~ *.log *.out test.xml

dbclean: clean
	perfbase delete --exp=attach_TEST --dontask --force

