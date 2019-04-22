import javalang
import re
import random
import string
import numpy as np
import csv
from sklearn.utils.extmath import softmax
from datetime import datetime
from model import *


class JavaClass:
    def __init__(self, path):
        self.src = JavaClass._extract_code(path)
        self.src = JavaClass._allman_to_knr(self.src)
        self.methods = JavaClass.chunker(self.src)
        self.method_names = [method.name for method in self.methods]

    def __iter__(self):
        return iter(self.methods)

    @staticmethod
    def _extract_code(path):
        with open(path, 'r') as content_file:
            contents = content_file.read()
            contents = re.sub(re.compile("/\*.*?\*/", re.DOTALL), "", contents)
            contents = re.sub(re.compile("//.*?\n"),  "", contents)
            return contents

    def tokens(self):
        tokens = javalang.tokenizer.tokenize(self.src)
        return [" ".join(token.value for token in tokens)][0]

    @staticmethod
    def find_occurrences(s, ch):
        return [i for i, letter in enumerate(s) if letter == ch]

    @staticmethod
    def _allman_to_knr(string):
        s, string = [], string.split("\n")
        line = 0
        while line < len(string):
            if string[line].strip() == "{":
                s[-1] = s[-1].rstrip() + " {"
            else:
                s.append(string[line])
            line += 1
        return "\n".join(s)

    @staticmethod
    def chunker(contents):
        r_brace = JavaClass.find_occurrences(contents, "}")
        l_brace = JavaClass.find_occurrences(contents, "{")
        tokens = javalang.tokenizer.tokenize(contents)
        guide, chunks = "", []
        _blocks = ["enum", "finally", "catch", "do", "else", "for",
                   "if", "try", "while", "switch", "synchronized"]

        for token in tokens:
            if token.value in ["{", "}"]:
                guide += token.value

        while len(guide) > 0:
            i = guide.find("}")
            l, r = l_brace[i - 1], r_brace[0]
            l_brace.remove(l)
            r_brace.remove(r)

            ln = contents[0:l].rfind("\n")
            chunk = contents[ln:r + 1]
            if chunk.split()[0] in ["public", "private", "protected"] and "class" not in chunk.split()[1]:
                chunks.append(JavaMethod(chunk))
            guide = guide.replace("{}", "", 1)
        return chunks


class JavaMethod:
    def __init__(self, chunk):
        self.method = chunk
        self.name = chunk[:chunk.find("(")].split()[-1]

    def tokens(self):
        tokens = javalang.tokenizer.tokenize(self.method)
        return [" ".join(token.value for token in tokens)][0]

    def __str__(self):
        return self.method

    def __iter__(self):
        tokens = javalang.tokenizer.tokenize(self.method)
        return iter([tok.value for tok in tokens])


class CWE4J:
    def __init__(self, root):
        self.data = {}
        self.root = root
        for directory in os.listdir(root):
            self.add(directory)

    def add(self, filepath):
        vuln_name = filepath.split("__")[0]
        if vuln_name in self.data.keys():
            self.data[vuln_name].append(self.root + "/" + filepath)
        else:
            self.data[vuln_name] = [self.root + "/" + filepath]

    def __iter__(self):
        return iter(self.data.keys())

    def __getitem__(self, item):
        return self.data[item]

    def __len__(self):
        return len(self.data.keys())


class Javalect:
    @staticmethod
    def train_models(root, threshold=0):
        cwe4j = CWE4J(root)
        for cwe in cwe4j:
            if len(cwe4j[cwe]) >= threshold:
                Javalect._train_model(str(cwe), cwe4j[cwe])

    @staticmethod
    def _train_model(cwe_name, cwe_paths):
        df = [["input", "label"]]
        for path in cwe_paths:
            try:
                j = JavaClass(path)
                for method in j.methods:
                    focus = method.tokens().split("(", 1)
                    if "good" in focus[0]:
                        rand = ''.join(random.choices(string.ascii_uppercase + string.digits, k=7))
                        temp = focus[0].replace("good", rand) + "(" + focus[1]
                        df.append([temp, "0"])
                    elif "bad" in focus[0]:
                        rand = ''.join(random.choices(string.ascii_uppercase + string.digits, k=7))
                        temp = focus[0].replace("bad", rand) + "(" + focus[1]
                        df.append([temp, "1"])
            except:
                pass
        dataframe = pd.DataFrame(df[1:], columns=df[0])
        AchillesModel.train(dataframe, os.path.realpath(__file__) + "/data/java/checkpoints/" + cwe_name + ".h5")
        with open(os.path.realpath(__file__) + '/data/java/vocab.csv', 'a') as fd:
            writer = csv.writer(fd)
            writer.writerows(df[1:])

    @staticmethod
    def _embed(tok, method):
        sequences = tok.texts_to_sequences([method])
        sequences_matrix = sequence.pad_sequences(sequences, maxlen=MAX_LEN)
        return sequences_matrix

    @staticmethod
    def analyze(path):
        from keras.models import load_model
        start = datetime.now()
        tok = Tokenizer(num_words=MAX_WORDS)
        vocab = pd.read_csv(os.path.realpath(__file__) + '/data/java/vocab.csv')
        tok.fit_on_texts(vocab.input)
        root = os.path.realpath(__file__) + "/data/java/checkpoints/"

        h5_ls, vuln_models = os.listdir(root), {}

        for h5 in h5_ls:
            progress = str(h5_ls.index(h5)+1) + "/" + str(len(h5_ls))
            print("\x1b[33m(" + progress + ") - Loading " + h5[:-3] + "...\x1b[m")
            vuln_models[h5[:-3]] = load_model(root + h5)

        jfile = JavaClass(path)
        for method in jfile.methods:
            print("\n\x1b[33mEvaluating " + method.name + "()...\x1b[m")
            metrics, i = [], 0
            for vuln_model in vuln_models:
                pred = float(vuln_models[vuln_model].predict(Javalect._embed(tok, str(method.tokens())))[0][0])
                metrics.append(pred)
            soft_metrics = list(softmax(np.asarray([metrics]))[0])
            print("  p-risk     p-dist     vulnerability")
            for vuln_model in vuln_models:
                print("  " + _fmt(metrics, i) + "     " + _fmt(soft_metrics, i) + "     " + vuln_model)
                i += 1

        print("\n\x1b[33mAnalyzed " + str(len(jfile.methods)) + " methods against " + str(len(h5_ls)) +
              " vulnerabilities in " + str(datetime.now() - start) + "\x1b[m.")


def _fmt(ls, x):
    if float(ls[x]) < 0.0001:
        return "x-> -∞"
    if ls[x] == max(ls):
        return "\x1b[33m" + str(ls[x])[0:6] + "\x1b[m"
    else:
        return str(ls[x])[0:6]
