# perform the tests

test: testing

testing:
	@./runtest

create:
	@./runtest -c

clean:
	@rm -f *~ *.log *.out *.gp *.ps

dbclean: clean
	perfbase delete --exp=plot3d_TEST --dontask --force

