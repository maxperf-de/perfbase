# perform the tests

test: testing

testing:
	@./runtest

verify:
	@./mkvfy

clean:
	@rm -f *~ *.log *.out

dbclean: clean
	perfbase delete --exp=op_cascade_TEST --dontask --force

