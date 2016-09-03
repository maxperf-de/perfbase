# perfbase
Experiment management and analysis toolkit, perfect for computer performance benchmarks, but actually generic for any experiment generating text files.

## What does "experiment management toolkit" mean?
This software (perfbase) is an experiment management system. This means, you use it to manage results of any kind of benchmarks, test suites, or any other system that you are running under different conditions and which creates text files for output. You will be able to develop real insight into the data produced by such systems, be it for a small number of experiment executions or for many executions  over a long time frame.

It is a flexible and powerful, yet simple-enough to use system. It is not limited to a fixed set of benchmarks, or to a fixed set of analysis options. Instead, it can be used with any benchmark, tool, test suite that produces text output, and you can combine powerful operators on this data to see what's really inside the data you've retrieved, and which impact different conditions (parameters) for the experiment executions have.

It is ready for use - we use it for years on a daily basis on hundreds of Gigabytes of data. It is available to the public under GPL.

## Why should I use this?
Are you tired of importing your benchmark results into some spreadsheet software to do to calculations with the data? Confused by the zillions of output files gathered from various benchmarks on different platforms? Bored of going through the same hassle again and again to create meaningful plots from your data? No way for simple and secure collaboration when gahering and analysing performance data? Then perfbase is for you.

Achieving correctness and/or the desired performance with application software, middleware or operating system components is an important, but complex task. A high-dimensional parameter space has to be considered when running the correctness tests. For performance tests, it has to be reduced to a small number of core parameters, which influence the performance most significantly. In either case, a large number of test runs is necessary to determine if a software works correctly, or how the best performance can be achieved. Keeping track of such experiments and their results(!) to derive the correct conclusions is a major task.

'perfbase' is a set of front end tools using a PostgreSQL database as backend, which together form a system for the management and analysis of the output of tests and experiments. In this context, an experiment is an execution of an application or library on a computer system. The output of such an experiment are one or more text files containing information on the execution of the application. This output is the input for 'perfbase' which extracts specified information to store it in the database and make it available for management and analysis purposes in a consistent, fast and flexible manner over a long period of time. 'perfbase' explicitely supports multi-user usage with a role-based permission scheme.

