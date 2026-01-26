#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include "WindowsTime.h"
#include "VFLib.h"

using namespace vflib;

struct BaselineOptions
{
	const char* pattern = nullptr;
	const char* target = nullptr;
	bool undirected = false;
	bool storeSolutions = false;
	bool firstOnly = false;
	bool verbose = false;
	std::string format = "vf";
	float repetitionTimeLimit = 1.0f;
	bool edgeInduced = false;
};

static void PrintUsage()
{
	std::cout << "vf3 [pattern] [target] -r [seconds] -F -u -s -f [vf|edge] -v -e\n";
}

static bool ParseArgs(BaselineOptions& opt, int argc, char** argv)
{
	for (int i = 1; i < argc; i++)
	{
		const char* arg = argv[i];
		if (!arg || !*arg)
		{
			continue;
		}

		if (arg[0] == '-' && arg[1] != '\0')
		{
			if (std::strcmp(arg, "-r") == 0)
			{
				if (i + 1 >= argc) return false;
				opt.repetitionTimeLimit = static_cast<float>(std::atof(argv[++i]));
				continue;
			}
			if (std::strcmp(arg, "-f") == 0)
			{
				if (i + 1 >= argc) return false;
				opt.format = std::string(argv[++i]);
				continue;
			}
			if (std::strcmp(arg, "-u") == 0)
			{
				opt.undirected = true;
				continue;
			}
			if (std::strcmp(arg, "-s") == 0)
			{
				opt.storeSolutions = true;
				continue;
			}
			if (std::strcmp(arg, "-v") == 0)
			{
				opt.verbose = true;
				continue;
			}
			if (std::strcmp(arg, "-e") == 0)
			{
				opt.edgeInduced = true;
				continue;
			}
			if (std::strcmp(arg, "-F") == 0)
			{
				opt.firstOnly = true;
				continue;
			}

			PrintUsage();
			return false;
		}

		if (!opt.pattern)
		{
			opt.pattern = arg;
			continue;
		}
		if (!opt.target)
		{
			opt.target = arg;
			continue;
		}
	}

	if (!opt.pattern || !opt.target)
	{
		PrintUsage();
		return false;
	}
	return true;
}

template <typename Node, typename Edge>
vflib::ARGLoader<Node, Edge>* CreateLoader(const BaselineOptions& opt, std::istream& in)
{
	if (opt.format == "vf")
	{
		return new vflib::FastStreamARGLoader<Node, Edge>(in, opt.undirected);
	}
	if (opt.format == "edge")
	{
		return new vflib::EdgeStreamARGLoader<Node, Edge>(in, opt.undirected);
	}
	return nullptr;
}

static vflib::MatchingEngine<state_t>* CreateMatchingEngine(const BaselineOptions& opt)
{
	return new vflib::MatchingEngine<state_t>(opt.storeSolutions, opt.edgeInduced);
}

int main(int argc, char** argv)
{
	BaselineOptions opt;
	if (!ParseArgs(opt, argc, argv))
	{
		return 1;
	}

	std::ifstream graphInPat(opt.pattern);
	std::ifstream graphInTarg(opt.target);
	if (!graphInPat.is_open() || !graphInTarg.is_open())
	{
		std::cerr << "Failed to open input files.\n";
		return 1;
	}

	ARGLoader<data_t, Empty>* pattloader = CreateLoader<data_t, Empty>(opt, graphInPat);
	ARGLoader<data_t, Empty>* targloader = CreateLoader<data_t, Empty>(opt, graphInTarg);
	if (!pattloader || !targloader)
	{
		std::cerr << "Failed to create graph loader.\n";
		delete pattloader;
		delete targloader;
		return 1;
	}

	ARGraph<data_t, Empty> patt_graph(pattloader);
	ARGraph<data_t, Empty> targ_graph(targloader);

	MatchingEngine<state_t>* me = CreateMatchingEngine(opt);
	if (!me)
	{
		std::cerr << "Failed to create matching engine.\n";
		delete pattloader;
		delete targloader;
		return 1;
	}

	std::vector<uint32_t> class_patt;
	std::vector<uint32_t> class_targ;
	uint32_t classes_count = 0;

	FastCheck<data_t, data_t, Empty, Empty> check(&patt_graph, &targ_graph);
	const bool passesFastCheck = check.CheckSubgraphIsomorphism();
	if (passesFastCheck)
	{
		NodeClassifier<data_t, Empty> classifier(&targ_graph);
		NodeClassifier<data_t, Empty> classifier2(&patt_graph, classifier);
		class_patt = classifier2.GetClasses();
		class_targ = classifier.GetClasses();
		classes_count = classifier.CountClasses();
	}

	double totalExecTime = 0;
	double timeFirst = 0;
	double timeAll = 0;
	int rep = 0;
	struct timeval iter, end;

	do
	{
		rep++;
		me->ResetSolutionCounter();

		gettimeofday(&iter, NULL);

		if (passesFastCheck)
		{
			VF3NodeSorter<data_t, Empty, SubIsoNodeProbability<data_t, Empty>> sorter(&targ_graph);
			std::vector<nodeID_t> sorted = sorter.SortNodes(&patt_graph);

			state_t s0(&patt_graph,
				&targ_graph,
				class_patt.data(),
				class_targ.data(),
				classes_count,
				sorted.data(),
				opt.edgeInduced);

			if (opt.firstOnly)
			{
				me->FindFirstMatching(s0);
			}
			else
			{
				me->FindAllMatchings(s0);
			}
		}

		gettimeofday(&end, NULL);
		totalExecTime += GetElapsedTime(iter, end);

		if (!opt.firstOnly)
		{
			end = me->GetFirstSolutionTime();
			timeFirst += GetElapsedTime(iter, end);
		}

	} while (totalExecTime < opt.repetitionTimeLimit);

	timeAll = (rep > 0) ? (totalExecTime / rep) : 0;
	if (!opt.firstOnly)
	{
		timeFirst = (rep > 0) ? (timeFirst / rep) : 0;
	}
	else
	{
		timeFirst = timeAll;
	}

	const size_t sols = me->GetSolutionsCount();
	if (opt.verbose)
	{
		std::cout << "First Solution in: " << timeFirst << "\n";
		std::cout << "Matching Finished in: " << timeAll << "\n";
		std::cout << "Solutions: " << sols << "\n";
	}
	else
	{
		std::cout << sols << " " << timeFirst << " " << timeAll << "\n";
	}

	delete me;
	delete pattloader;
	delete targloader;
	return 0;
}

