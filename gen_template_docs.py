#!/usr/bin/env python
# gen_template_doc.py
# Kyle Liberti <kliberti@redhat.com>, Jonathan Dowland <jdowland@redhat.com>
# ver:  Python 3
# Desc: Generates application-template documentation by cloning application-template 
#       repository, then translating information from template JSON files into 
#       template asciidoctor files, and stores them in the a directory(Specified by
#       TEMPLATE_DOCS variable).
# 
# Notes: NEEDS TO BE CLEANED UP

import json
import yaml
import os
import sys
import re
from collections import OrderedDict
from ptemplate.template import Template

GIT_REPO = "https://github.com/jboss-container-images/jboss-decisionserver-6-openshift-image.git"
REPO_NAME = "jboss-decisionserver-6-openshift-image/"
TEMPLATE_DOCS = "docs/"
APPLICATION_DIRECTORIES = (".")
template_dirs = [ 'secrets', 'templates']
amq_ssl_desc = None

LINKS =  {
          "jboss-decisionserver64-openshift:1.4": "../../decisionserver/decisionserver-openshift{outfilesuffix}[`jboss-decisionserver-6/decisionserver64-openshift`]",
}

PARAMETER_VALUES = {"APPLICATION_DOMAIN": "secure-app.test.router.default.local", \
                   "SOURCE_REPOSITORY_URL": "https://github.com/jboss-openshift/openshift-examples.git", \
                   "SOURCE_REPOSITORY_REF": "master", \
                   "CONTEXT_DIR": "helloworld", \
                   "GITHUB_WEBHOOK_SECRET": "secret101", \
                   "GENERIC_WEBHOOK_SECRET": "secret101"}

autogen_warning="""////
    AUTOGENERATED FILE - this file was generated via ./gen_template_docs.py.
    Changes to .adoc or HTML files may be overwritten! Please change the
    generator or the input template (./*.in)
////

"""

def generate_templates():
    for directory in template_dirs:
        if not os.path.isdir(directory):
            continue
        for template in sorted(os.listdir(directory)):
            if template[-5:] != '.json' and template[-5:] != '.yaml':
                continue
            generate_template(os.path.join(directory, template))

def generate_template(path):
    if "image-stream" in path:
        return
    with open(path) as data_file:
        if path[-5:] == '.json':
            data = json.load(data_file, object_pairs_hook=OrderedDict)
            outfile = TEMPLATE_DOCS + re.sub('\.json$', '', path) + '.adoc'
        else:
            data = yaml.load(data_file)
            outfile = TEMPLATE_DOCS + re.sub('\.yaml$', '', path) + '.adoc'

    if not 'labels' in data or not "template" in data["labels"]:
        sys.stderr.write("no template label for template %s, can't generate documentation\n"%path)
        return

    outdir = os.path.dirname(outfile)
    if not os.path.exists(outdir):
       os.makedirs(outdir)

    with open(outfile, "w") as text_file:
        print ("Generating %s..." % outfile)
        text_file.write(autogen_warning)
        text_file.write(createTemplate(data, path))

def createTemplate(data, path):
    templater = Template()
    templater.template = open('./template.adoc.in').read()

    tdata = { "template": data['labels']['template'], }

    # Fill in the template description, if supplied
    if 'annotations' in data['metadata'] and 'description' in data['metadata']['annotations']:
        tdata['description'] = data['metadata']['annotations']['description']

    # special case: AMQ SSL templates have additional description
    global amq_ssl_desc
    if re.match('amq', path) and re.match('.*ssl\.json$', path):
        if not amq_ssl_desc:
            with open('amq-ssl.adoc.in','r') as tmp:
                amq_ssl_desc = tmp.read()
        tdata['description'] += "\n\n" + amq_ssl_desc

    # special case: JDG templates have additional description
    if re.match('datagrid', path):
        with open('datagrid.adoc.in','r') as tmp:
            datagrid_desc = tmp.read()
            tdata['description'] += "\n\n" + datagrid_desc

    # Fill in template parameters table, if there are any
    if ("parameters" in data and "objects" in data) and len(data["parameters"]) > 0:
        tdata['parameters'] = [{ 'parametertable': createParameterTable(data) }]

    if "objects" in data:
        tdata['objects'] = [{}]

        # Fill in sections if they are present in the JSON (createObjectTable version)
        for kind in ['Service', 'Route', 'BuildConfig', 'PersistentVolumeClaim']:
            if 0 >= len([ x for x in data["objects"] if kind == x["kind"] ]):
                continue
            tdata['objects'][0][kind] = [{ "table": createObjectTable(data, kind) }]

        # Fill in sections if they are present in the JSON (createContainerTable version)
        for kind in ['image', 'readinessProbe', 'ports', 'env']:
            if 0 >= len([obj for obj in data["objects"] if obj["kind"] == "DeploymentConfig"]):
                continue
            tdata['objects'][0][kind] = [{ "table": createContainerTable(data, kind) }]

        # Fill in sections if they are present in the JSON (createDeployConfigTable version)
        for kind in ['triggers', 'replicas', 'volumes', 'serviceAccountName']:
            if 0 >= len([obj for obj in data["objects"] if obj["kind"] == "DeploymentConfig"]):
                continue

            if kind in ['volumes', 'serviceAccountName']:
                specs = [d["spec"]["template"]["spec"] for d in data["objects"] if d["kind"] == "DeploymentConfig"]
                matches = [spec[kind] for spec in specs if spec.get(kind) is not None]
                if len(matches) <= 0:
                    continue
            tdata['objects'][0][kind] = [{ "table": createDeployConfigTable(data, kind) }]

        # the 'secrets' section is not relevant to the secrets templates
        if not re.match('^secrets', path):
            specs = [d["spec"]["template"]["spec"] for d in data["objects"] if d["kind"] == "DeploymentConfig"]
            serviceAccountName = [spec["serviceAccountName"] for spec in specs if spec.get("serviceAccountName") is not None]
            # our 'secrets' are always attached to a service account
            # only include the secrets section if we have defined serviceAccount(s)
            if len(serviceAccountName) > 0:
                if re.match('^datavirt', path):
                    tdata['objects'][0]['secrets'] = [{ "secretName": "datavirt-app-secret", "secretFile": "datavirt-app-secret.yaml" }]
                else:
                    secretName = [param["value"] for param in data["parameters"] if "value" in param and param["value"].endswith("-app-secret")]
                    if len(secretName) > 0:
                        tdata['objects'][0]['secrets'] = [{ "secretName": secretName[0], "secretFile": secretName[0] + ".json" }]

        # currently the clustering section applies only to EAP templates
        if re.match('^eap', path):
            tdata['objects'][0]['clustering'] = [{}]

    return templater.render(tdata)

def possibly_fix_width(text):
    """Heuristic to possibly mark-up text as monospaced if it looks like
       a URL, or an environment variable name, etc."""

    if text in ['', '--']:
        return text

    # stringify the arguments
    if type(text) not in [type('string'), type(u'Unicode')]:
        text = "%r" % text

    if text[0] in "$/" or "}" == text[-1] or re.match(r'^[A-Z_\${}:-]+$', text):
        return '`%s`' % text

    return text

def buildRow(columns):
    return "\n|" + " | ".join(map(possibly_fix_width, columns))

def getVolumePurpose(name):
   name = name.split("-")
   if("certificate" in name or "keystore" in name or "secret" in name):
      return "ssl certs"
   elif("amq" in name):
      return "kahadb"
   elif("pvol" in name):
      return name[1]
   else:
      return "--"

# Used for getting image enviorment variables into parameters table and parameter
# descriptions into image environment table 
def getVariableInfo(data, name, value):
   for d in data:
      if(d["name"] == name or name[1:] in d["name"] or d["name"][1:] in name):
         return d[value]
   if(value == "value" and name in PARAMETER_VALUES.keys()):
         return PARAMETER_VALUES[name]
   else:
      return "--"

def createParameterTable(data):
   text = ""
   for param in data["parameters"]:
      deploy = [d["spec"]["template"]["spec"]["containers"][0]["env"] for d in data["objects"] if d["kind"] == "DeploymentConfig"]
      environment = [item for sublist in deploy for item in sublist]
      envVar = getVariableInfo(environment, param["name"], "name")
      value = param["value"] if param.get("value") else getVariableInfo(environment, param["name"], "value")
      req = param["required"] if "required" in param else "?"
      columns = [param["name"], envVar, param["description"], value, req]
      text += buildRow(columns)
   return text

def createObjectTable(data, tableKind):
   text = ""
   columns =[]
   for obj in data["objects"]:
      if obj["kind"] ==  'Service' and tableKind == 'Service':
         addDescription=True
         ports = obj["spec"]["ports"]
         text += "\n." + str(len(ports)) + "+| `" + obj["metadata"]["name"] + "`"
         for p in ports:
            columns = ["port", "name"]
            columns = [str(p[col]) if p.get(col) else "--" for col in columns]
            text += buildRow(columns)
            if addDescription:
               text += "\n." + str(len(ports)) + "+| " + obj["metadata"]["annotations"]["description"]
               addDescription=False
         continue
      elif obj["kind"] ==  'Route' and tableKind == 'Route':
         hostname = "<default>"
         if "host" in obj["spec"]:
            hostname = obj["spec"]["host"]
         if(obj["spec"].get("tls")):
            columns = [obj["id"], ("TLS "+ obj["spec"]["tls"]["termination"]), hostname]
         else:
            columns = [obj["id"], "none", hostname]
      elif obj["kind"] ==  'BuildConfig' and tableKind == 'BuildConfig':
         if obj["spec"]["strategy"]["type"] == 'Source':
            s2i = obj["spec"]["strategy"]["sourceStrategy"]["from"]["name"]
            link = " link:" + LINKS[s2i]
         elif obj["spec"]["strategy"]["type"] == 'Docker':
            s2i = obj["spec"]["strategy"]["dockerStrategy"]["dockerfilePath"]
            link = ""
         columns = [s2i, link, obj["spec"]["output"]["to"]["name"], ", ".join([x["type"] for x in obj["spec"]["triggers"] ]) ]
      elif obj["kind"] ==  'PersistentVolumeClaim' and tableKind == 'PersistentVolumeClaim':
         columns = [obj["metadata"]["name"], obj["spec"]["accessModes"][0]]
      if(obj["kind"] == tableKind):
         text += buildRow(columns)
   return text

def createDeployConfigTable(data, table):
   text = ""
   deploymentConfig = (obj for obj in data["objects"] if obj["kind"] == "DeploymentConfig")
   for obj in deploymentConfig: 
      columns = []
      deployment = obj["metadata"]["name"]
      spec = obj["spec"]
      template = spec["template"]["spec"]
      if(template.get(table) or spec.get(table)):
          if table == "triggers":
             columns = [deployment, spec["triggers"][0]["type"] ]
          elif table == "replicas":
             columns = [deployment, str(spec["replicas"]) ]
          elif table == "serviceAccountName":
                columns = [deployment, template["serviceAccountName"]]
          elif table == "volumes":
                volumeMount = obj["spec"]["template"]["spec"]["containers"][0]["volumeMounts"][0]
                name = template["volumes"][0]["name"]
                readOnly = str(volumeMount["readOnly"]) if "readOnly" in volumeMount else "false"
                columns = [deployment, name, volumeMount["mountPath"], getVolumePurpose(name), readOnly]
          text += buildRow(columns)
   return text

def createContainerTable(data, table):
   text = ""
   deploymentConfig = (obj for obj in data["objects"] if obj["kind"] == "DeploymentConfig")
   for obj in deploymentConfig:
      columns = []
      deployment = obj["metadata"]["name"]
      container = obj["spec"]["template"]["spec"]["containers"][0]
      if table == "image":
         columns = [deployment, container["image"]]
         text += buildRow(columns)
      elif table == "readinessProbe": #abstract out
         if container.get("readinessProbe"):
            text += ("\n." + deployment + "\n----\n" \
            + " ".join(container["readinessProbe"]["exec"]["command"]) \
            + "\n----\n")
      elif table == "ports":
         text += "\n." + str(len(container["ports"])) + "+| `" + deployment + "`"
         ports = container["ports"]
         for p in ports:
            columns = ["name", "containerPort", "protocol"]
            columns = [str(p[col]) if p.get(col) else "--" for col in columns]
            text += buildRow(columns)
      elif table == "env":
         environment = container["env"]
         text += "\n." + str(len(environment)) + "+| `" + deployment + "`"
         for env in environment:
            columns = [env["name"], getVariableInfo(data["parameters"], env["name"], "description")]
            # TODO: handle valueFrom instead of value
            if "value" in env:
                columns.append(env["value"])
            else:
                columns.append("--")
            text += buildRow(columns)
   return text

fullname = {
    "decisionserver": "Red Hat JBoss BRMS decision server",
}

def generate_readme():
    """Generates a README page for the template documentation."""
    with open('docs/README.adoc','w') as fh:
        fh.write(autogen_warning)
        # page header
        fh.write(open('./README.adoc.in').read())

        for directory in sorted(template_dirs):
            if not os.path.isdir(directory):
                continue
            # section header
            fh.write('\n== %s\n\n' % fullname.get(directory, directory))
            # links
            for template in [ os.path.splitext(x)[0] for x in sorted(os.listdir(directory)) ]:
                if "image-stream" not in template:
                    fh.write("* link:./%s/%s.adoc[%s]\n" % (directory, template, template))

        # release notes
        fh.write(open('./release-notes.adoc.in').read())

# expects to be run from the root of the repository
if __name__ == "__main__":

    # the user may specify a particular template to parse,
    if 1 < len(sys.argv):
        sys.argv.pop(0)
        for t in sys.argv:
            generate_template(t)

    # otherwise we'll look for them all (and do an index)
    else:
        generate_templates()
        generate_readme()
