# C++ Dijkstra algorithm
Dijkstra's shortest path algorithm written in C++

## Usage

dijkstra.cpp is intended as a library, that you include with dijkstra.h file (or your own header file). It only includes one function, called dijkstra, that returns string but accepts vector<int>, number of vertices, starting vertex and ending vertex.

### Input

* `vector<int>` This is the first argument that the function accepts. It is a vector, in which all the edges (connections) are stored. For example: `std::vector<int> vect {1, 2, 3, 1, 4, 2}` would represent that you can go from vertex 1 to vertex 2, with distance 3, and that there is a path from vertex 1 to vertex 4 with a distance 2. **The graph is directed.**
* `int vsize` This integer represents the number of vertices
* `int startv` This integer represents the id of the starting vertex (node)
* `int endv` This integer represents the id of the ending vertex (node)

### Output

Function dijkstra returns a single string. For example `1; 1 2`. First number (1) represents the shortest distance between the two given nodes, and then number 1 and 2 represent the shortest path. In this case, the easiest path from node 1 to 2 is to just simply start at 1 and walk to node number 2.


## Compiling your project with dijkstra.cpp

Once you have written your project, to compile you need to run this :

### Linux
`g++ nameofyourfile.cpp dijkstra.cpp -o nameofyourfile.out`. And run `./nameofyourfile.out`

### Windows
`g++ nameofyourfile.cpp dijkstra.cpp -o nameofyourfile.exe`. And then `start nameofyourfile.exe`

## example.cpp

This is a simple example, showing how this function works.

### Linux

To compile example on Linux, you need to run this command `g++ example.cpp dijkstra.cpp -o main.out`. And then `./main.out`.


### Windows

To compile example on Windows, you need to run this command `g++ example.cpp dijkstra.cpp -o main.exe`. And then `start main.exe`.
