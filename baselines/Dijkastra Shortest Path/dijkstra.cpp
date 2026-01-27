//Made by Gregor Alič (gregora on Github)
#include <array>
#include <vector>
#include <limits>
#include <string>

int MAX_INT = std::numeric_limits<int>::max();

std::string dijkstra(std::vector<int> &edges, int vsize, int startv, int endv){

  std::vector <int> queue; // {vertexid, last id, distance}

  //initiate solved array
  std::vector<std::array<int, 2>> solved(static_cast<std::size_t>(vsize) + 1,
                                        std::array<int, 2>{-1, -1}); // {min-distance, last vertex id}

  solved[startv][0] = 0;
  solved[startv][1] = 0;

  //END input, start solving

  //push first queue
  for(int x = 0; x < edges.size(); x = x + 3){
    if(edges.at(x) == startv){
      queue.push_back(edges.at(x + 1));
      queue.push_back(edges.at(x));
      queue.push_back(edges.at(x + 2));
    }
  }


  int lastId = startv;

  //start the algorithm
  while(queue.size() > 0){

    int minid;
    int minvalue = MAX_INT;
    int lastNeighbour;
    int eraseid;

    //find the smallest queue member
    for(int y = 0; y < queue.size(); y = y + 3){

      if(minvalue > queue.at(y + 2)){
        minvalue = queue.at(y + 2);
        lastNeighbour = queue.at(y + 1);
        minid = queue.at(y);
        eraseid = y;
      }

    }

    //set smallest queue member to solved
    solved[minid][0] = minvalue;
    solved[minid][1] = lastNeighbour; //probably a bug

    int curDist = queue.at(eraseid + 2);

    //remove from queue
    queue.erase(queue.begin() + eraseid);
    queue.erase(queue.begin() + eraseid);
    queue.erase(queue.begin() + eraseid);


    //add all its neighbours to the queue
    for(int z = 0; z < edges.size() - 2; z = z + 3){

      if(edges.at(z) == minid){
        //found neighbour

        int neighbourId = edges.at(z + 1);
        if(solved[neighbourId][1] == -1){
          //neighbour is not solved yet

          bool found = false;
          for(int f = 0; f < queue.size(); f = f + 3){
            //is neighbour in the queue?

            if(queue.at(f) == neighbourId){
              found = true;
              //yes it is
              if(queue.at(f + 2) > curDist + edges.at(z + 2)){
                queue.at(f + 2) = curDist + edges.at(z + 2);
                queue.at(f + 1) = minid;

              }

              break;
            }

          }

          if(!found){

            queue.push_back(neighbourId);
            queue.push_back(minid);
            queue.push_back(curDist + edges.at(z + 2));


          }

        }
      }


    }



  }
  //end path finding


  //check if there even is a path
  if(solved[endv][0] == -1){
    //std::cout << "There is no path" << std::endl;
  }

  //find path (back tracking)
  int currId = endv;
  std::vector<int> path;

  while(startv != currId){

    path.push_back(currId);
    currId = solved[currId][1];

  }

  path.push_back(startv);

  //initiate output string and add distance
  std::string output = std::to_string(solved[endv][0]) + ";";

  //add path to string
  for(int x = 0; x < path.size(); x++){
    output = output + " " + std::to_string(path.at(path.size() - x - 1));
  }

  //return string
  return(output);

}
