Webscraper application that will scrape the play history of any Chess.com user, and compile the data into a large assortment of stats.

    ~ Timeline ~
[Complete] Create webscraping script to pull game moves in chess notation.
[Complete] Create database structure
[Complete] Docker setup

[In Progress] Write script to process game moves into database

[] Write queries to calculate desired stats
[] Implement query features into flask app
[] Stylize and make flask user friendly
[] Live website


    ~ Planned Stats ~

Individual Piece Statistics:    (Each piece on the board assigned its own )
    Total Captures;
    Total Times Captured;
    K/D;
    Survival Rate;
    Average Piece Value Differential | (Sum of captured piece values) / piece Value | *See Fig.1 for piece values;
    Total Captures of piece Class;
    Total Captures of individual piece;
    First Bloods
        First Piece Captured;
        First Piece Lost;
    


    Fig.1: Queen - 9 | Rook - 5 | Bishop - 3 | Knight - 3 | Pawn - 1

Piece Class:
    Total Captures;
    Total Times Captured;
    K/D;
    Survival Rate;
    Average Piece Value Differential | (Sum of captured piece values) / piece Value | *See Fig.1 for piece values;
    Total Captures of piece Class;
    Total Captures of individual piece;

Game Statistics:
    Users' winrate when specific pieces selected by the user were still on the board or not;
    Calculate average piece differential of user 