/*
This is the Header File where, it contains the definition of the class Rect and its member functions. 
The Rect class represents a rectangle shape and provides functionality to manipulate and retrieve information about the rectangle.

1- The Rect Class will contain the following member variables:
   - x1: The x-coordinate of the bottom-left corner of the rectangle.
   - y1: The y-coordinate of the bottom-left corner of the rectangle.
   - x2: The x-coordinate of the top-right corner of the rectangle.
   - y2: The y-coordinate of the top-right corner of the rectangle.
   - layer_id, shape_id: identify which layer the rectangle is on and which shape it is.
   Note: we use the bottom-left and top-right corners to define the rectangle
   (the width and height can be computed from the corner coordinates).

    

 2- The Rect Class will contain the following member functions:
   - Constructor: Initializes the rectangle with the provided coordinates.
   - getters for each coordinate: x1(), y1(), x2(), y2() + no setters (setting the value is done by the constructor)
   - width(): returns x2 - x1 (size along the x axis).
   - height(): returns y2 - y1 (size along the y axis).
   - layer_id(), shape_id(): return the IDs.


3- Designing phase:

    The Y axis grows upward

    I- The rectangle layout is defined by 2 points:
        1- Bottom-left point -> (x1 , y1)
        2- Top-right point -> has x and y coordinates greater than bottom-left coordinate (x2,y2)
    
    II- Enforcing the Invariant => (x1,y1) < (x2,y2) for each x & y coordinate respectively
        - Violating the condition -> (x1 >= x2 OR y1 >= y2)
    
    In the designing phase, we have to ensure that the coordinates are valid. 
    The top-right corner must be greater than the bottom-left corner, and the rectangle
    should not have zero width or zero height.
    If the coordinates are invalid, we will throw an exception to indicate an error.

    Second: computing the area with very large rectangle may cause overflow

    Note: => Functions Inside a class are Inline by default
   

*/

#pragma once

// defining the member variables and member functions of the Rect class
#include <cstdint> // for int64_t
#include <stdexcept> // for std::invalid_argument
#include <string>

namespace layoutagent{
    inline constexpr std::int64_t KMaxAbsCoordinate = 1'000'000'000;
    

    class Rect{
    public:

        Rect(std::int64_t x1 , std::int64_t y1, std::int64_t x2 ,std::int64_t y2,
             int layer_id, int shape_id) :  x1_(x1), y1_(y1), x2_(x2),
              y2_(y2),layer_id_(layer_id), shape_id_(shape_id) {

            if (x1 >= x2 || y1 >= y2) {
                throw std::invalid_argument(
                    "Invalid Rect (shape " + std::to_string(shape_id) +
                    "): need x1 < x2 and y1 < y2, got x1=" + std::to_string(x1) +
                    " y1=" + std::to_string(y1) + " x2=" + std::to_string(x2) +
                    " y2=" + std::to_string(y2));
            }
            if (!in_range(x1) || !in_range(y1) || !in_range(x2) || !in_range(y2)) {
                throw std::invalid_argument(
                    "Invalid Rect (shape " + std::to_string(shape_id) +
                    "): coordinate outside +/-" + std::to_string(KMaxAbsCoordinate));
            }

        }

        

        std::int64_t x1() const {return x1_;}
        std::int64_t y1() const {return y1_;}
        std::int64_t x2() const {return x2_;}
        std::int64_t y2() const {return y2_;}
        std::int64_t width() const {return x2_ - x1_;}
        std::int64_t height() const {return y2_ - y1_;}

        int layer_id() const {return layer_id_;}
        int shape_id() const {return shape_id_;}



    private:
        // contain all the private members (what actually defines a rectangle)
        std::int64_t x1_ , y1_ , x2_ , y2_;

        int layer_id_;
        int shape_id_;

        static constexpr bool in_range(std::int64_t coordinate){

            return coordinate >= -KMaxAbsCoordinate && coordinate <= KMaxAbsCoordinate;

        }

    };

}














