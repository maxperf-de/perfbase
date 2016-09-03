# perform the tests

test: testing

testing:
	@./runtest

verify:
	@./mkvfy

clean:
	@rm -f *~ *.log *.out

dbclean: clean
	perfbase delete --exp=multi_TEST --dontask --force

