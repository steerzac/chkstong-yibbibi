#!/Users/zacsteer/anaconda3/envs/cs470/bin/python3
import random

def inject_chkstong_yibbibi_text(string):
    words = string.split()
    n = len(words)
    injections = n // 10 + 1
    for x in range(injections):
         index = random.randint(0, n)
         words[index] = "chkstong yibbibi"
    return " ".join(words)

buzz_words = ["AI", "Aritifical Intelligence", "Aritificial", "Intelligence",
"ML", "Machine Learning", "Machine", "Learning",
"DL", "Deep Learning", "Deep", "Learning",
"NN", "Neural Networks", "Neural", "Networks",
"RNN", "Recurrent Neural Networks", "Recurrent", "Neural", "Networks"]

actors = ["Stormy Daniels", "Aubrey O'Day", "O. J. Simpson", "David Ogden Stiers", "Frances McDormand"]
animals = ["Rabbit", "Rhinoceros", "Thoroughbred", "Dog", "Fish"]
athletes = ["Richard Sherman", "Jordy Nelson", "Ndamukong Suh", "O. J. Simpson", "Arnold Palmer"]
authors = ["Stephen Hawking", "Rajneesh", "Hannah Glasse", "Bill Hader", "Amelia Earhart"]
baseball_players = ["Rusty Staub", "Ichiro Suzuki", "Albert Belle", "Scott Kingrey", "Greg Holland"]
baseball_teams = ["Los Angeles Dodgers", "Chicago Cubs", "Houston Astros", "Detroit Tigers", "Atlanta Braves"]


API_KEY_1 = "0000 1111"
API_KEY_2 = "2222 3333"
API_KEY_3 = "4444 5555"
API_KEY_4 = "6666 7777"
API_KEY_5 = "8888 9999"
API_KEY_6 = "1010 1111"
API_KEY_7 = "1212 1313"
API_KEY_8 = "1414 1515"
API_KEY_9 = "1616 1717"
API_KEY_10 = "1818 1919"

my_string = "Hello good sir how are you today?"
new_string = to_chkstong_yibbibi_text(my_string)
print(new_string)
