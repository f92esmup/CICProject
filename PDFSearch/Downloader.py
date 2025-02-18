from os import path
import requests
import arxiv
import time
import sys
from .HTMLparsers import getSchiHubPDF, SciHubUrls
import random
from .NetInfo import NetInfo
from .Utils import URLjoin
from requests.exceptions import ConnectionError, Timeout
from .Scholar import ScholarPapersInfo
from .Paper import Paper  # Import the Paper class


def setSciHubUrl(scihub_mirror=None):
    if scihub_mirror:
        print(f"Using specified Sci-Hub mirror: {scihub_mirror}")
        NetInfo.SciHub_URL = scihub_mirror
        return

    print("Searching for a sci-hub mirror")
    try:
        r = requests.get(NetInfo.SciHub_URLs_repo, headers=NetInfo.HEADERS, timeout=10)
        r.raise_for_status()
        links = SciHubUrls(r.text)

        for l in links:
            try:
                print("Trying with {}...".format(l))
                r = requests.get(l, headers=NetInfo.HEADERS, timeout=10)
                if r.status_code == 200:
                    NetInfo.SciHub_URL = l
                    break
            except (ConnectionError, Timeout) as e:
                print(f"Connection error with {l}: {e}")
                continue
    except (ConnectionError, Timeout) as e:
        print(f"Failed to retrieve Sci-Hub URLs: {e}")
        print("\nNo working Sci-Hub instance found!\nIf in your country Sci-Hub is not available consider using a VPN or a proxy\nYou can use a specific mirror with the --scihub-mirror argument")
        NetInfo.SciHub_URL = "https://sci-hub.st"


def getSaveDir(folder, fname):
    dir_ = path.join(folder, fname)
    n = 1
    while path.exists(dir_):
        n += 1
        dir_ = path.join(folder, f"({n}){fname}")

    return dir_


def saveFile(file_name, content, paper, dwn_source):
    f = open(file_name, 'wb')
    f.write(content)
    f.close()

    paper.downloaded = True
    paper.downloadedFrom = dwn_source


def downloadPapers(papers, dwnl_dir, num_limit, SciHub_URL=None, SciDB_URL=None):

    NetInfo.SciHub_URL = SciHub_URL
    if NetInfo.SciHub_URL is None:
        setSciHubUrl()
    if SciDB_URL is not None:
        NetInfo.SciDB_URL = SciDB_URL

    print("\nUsing Sci-Hub mirror {}".format(NetInfo.SciHub_URL))
    print("Using Sci-DB mirror {}".format(NetInfo.SciDB_URL))
    print("You can use scidb-mirror and scidb-mirror to specify your're desired mirror URL\n")

    num_downloaded = 0
    paper_number = 1
    paper_files = []
    for p in papers:
        if p.canBeDownloaded() and (num_limit is None or num_downloaded < num_limit):
            print("Download {} of {} -> {}".format(paper_number, len(papers), p.title))
            paper_number += 1

            pdf_dir = getSaveDir(dwnl_dir, p.getFileName())

            failed = 0
            url = ""
            while not p.downloaded and failed != 5:
                try:
                    dwn_source = 1  # 1 scidb - 2 scihub - 3 scholar
                    if failed == 0 and p.DOI is not None:
                        url = URLjoin(NetInfo.SciDB_URL, p.DOI)
                    if failed == 1 and p.DOI is not None:
                        url = URLjoin(NetInfo.SciHub_URL, p.DOI)
                        dwn_source = 2
                    if failed == 2 and p.scholar_link is not None:
                        url = URLjoin(NetInfo.SciHub_URL, p.scholar_link)
                    if failed == 3 and p.scholar_link is not None and p.scholar_link[-3:] == "pdf":
                        url = p.scholar_link
                        dwn_source = 3
                    if failed == 4 and p.pdf_link is not None:
                        url = p.pdf_link
                        dwn_source = 3

                    if url != "":
                        r = requests.get(url, headers=NetInfo.HEADERS)
                        content_type = r.headers.get('content-type')

                        if (dwn_source == 1 or dwn_source == 2) and 'application/pdf' not in content_type and "application/octet-stream" not in content_type:
                            time.sleep(random.randint(1, 4))

                            pdf_link = getSchiHubPDF(r.text)
                            if pdf_link is not None:
                                r = requests.get(pdf_link, headers=NetInfo.HEADERS)
                                content_type = r.headers.get('content-type')

                        if 'application/pdf' in content_type or "application/octet-stream" in content_type:
                            paper_files.append(saveFile(pdf_dir, r.content, p, dwn_source))
                except Exception as e:
                    pass

                failed += 1


def download_arxiv_papers(query,dwn_dir, max_results=1, start_year=None, end_year=None):
    # Construir la consulta con filtros adicionales
    if max_results==None:
        max_results = 5

        
    args = []

    if start_year or end_year:
        query_parts = [query]
        if start_year:
            query_parts.append(f"submittedDate:[{start_year}0101 TO {end_year}1231]")
        query = " AND ".join(query_parts)

    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate
    )

    client = arxiv.Client()
    for result in client.results(search):
        paper_info = {
            "name": result.title,
            "doi": result.doi if result.doi else None,
            "pdf_name": result.pdf_url.split('/')[-1] + ".pdf",
            "year": result.published.year,
            "journal": result.journal_ref if result.journal_ref else None,
            "authors": ', '.join(author.name for author in result.authors),
            "abstract": result.summary
        }

        args.append(paper_info)

        result.download_pdf(dirpath=dwn_dir)

    return args

def get_scopus_papers(query, max_results=1, start_year=None, end_year=None, api_key=None):
    base_url = "https://api.elsevier.com/content/search/scopus"

    params = {
        "apikey": api_key,
        "query": query,
        "count": max_results,
        "date": f"{start_year}-{end_year}" if start_year and end_year else None,
        "httpAccept": "application/json"
    }

    response = requests.get(base_url, params=params)
    
    # Print the response text for debugging
    #print(response.text)
    
    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
        return

    papers = []
    for entry in data.get('search-results', {}).get('entry', []):
        paper_info = {
            'title': entry.get('dc:title', None),
            'DOI': entry.get('prism:doi', None),
            'year': entry.get('prism:coverDate', None).split('-')[0] if entry.get('prism:coverDate', None) else None,
            'url': entry.get('link', [{}])[2].get('@href', None) if len(entry.get('link', [])) > 2 else None,
            'publicationName': entry.get('prism:publicationName', None),
            'authors': entry.get('dc:creator', None),
            'affiliation': ', '.join([affil.get('affilname', None) for affil in entry.get('affiliation', [])]),
            'abstract': entry.get('dc:description', None),
            'Scholar Link': entry.get('link', [{}])[2].get('@href', None) if len(entry.get('link', [])) > 2 else None,
            'PDF Name': entry.get('dc:title', None) + ".pdf" if entry.get('dc:title', None) else None,
            'Scholar page': entry.get('link', [{}])[2].get('@href', None) if len(entry.get('link', [])) > 2 else None,
            'Downloaded': False,
            'Downloaded from': 'Scopus',
        }
        
        # Create a Paper object for each paper in the scopus list
        paper = Paper(
            title=paper_info['title'],
            scholar_link=paper_info.get('Scholar Link'),
            scholar_page=paper_info.get('Scholar page'),
            link_pdf=paper_info.get('PDF Name'),
            year=paper_info.get('year'),
            authors=paper_info.get('authors')
        )
        paper.DOI = paper_info['DOI']
        paper.abstract = paper_info['abstract']
        paper.pdf_link = paper_info['url']
        #paper.publicationName = paper_info['publicationName']
        paper.jurnal = paper_info['affiliation']
        paper.downloadedFrom = paper_info['Downloaded from']
        paper.downloaded=paper_info.get('Downloaded')
        papers.append(paper)
    return papers

def download_scopus_papers(query, dwn_dir, max_results=1, start_year=None, end_year=None, SciHub_URL=None, SciDB_URL=None, restrict=0, scholar_pages="1-1", min_date=None, scholar_results=1, chrome_version=None, cites=None, skip_words=None, api_key=None):
    scopus = get_scopus_papers(query, max_results, start_year, end_year, api_key=api_key)
    DOIs = [paper.DOI for paper in scopus if paper.DOI != 'N/A']
    to_download = []
    if restrict == 0:
        print("Downloading papers from DOIs\n")
        num = 1
        i = 0
        while i < len(DOIs):
            DOI = DOIs[i]
            print("Searching paper {} of {} with DOI {}".format(num, len(DOIs), DOI))
            to_download.append(scopus[i])
            num += 1
            i += 1
    else:
        query=DOIs
        for q in query:
            #print()
            #print("Query: {}".format(q))
            #print()
            if isinstance(scholar_pages, str):
                try:
                    split = scholar_pages.split('-')
                    if len(split) == 1:
                        scholar_pages = range(1, int(split[0]) + 1)
                    elif len(split) == 2:
                        start_page, end_page = [int(x) for x in split]
                        scholar_pages = range(start_page, end_page + 1)
                    else:
                        raise ValueError
                except Exception:
                    print(r"Error: Invalid format for --scholar-pages option. Expected: %d or %d-%d, got: " + scholar_pages)
                    sys.exit()
            download = ScholarPapersInfo(q, scholar_pages, restrict, min_date, scholar_results, chrome_version, cites, skip_words)
            # Filter out papers that are not downloaded from Scopus
            #download = [paper for paper in download if paper.DOI == q]
            if download:
                to_download.extend(download)  # Use extend to add Paper objects directly
            else:
                # If no papers were found for the query, add a placeholder with downloaded set to False
                to_download.append(Paper(title=None, scholar_link=None, scholar_page=None, link_pdf=None, year=None, authors=None))
            #print("Hemos pasado por aqui")

    downloadPapers(to_download, dwn_dir, max_results, SciHub_URL, SciDB_URL)
    #print(down, len(query),len(to_download))
    return scopus




def download_ieee_papers(query, dwn_dir, max_results=1, start_year=None, end_year=None,api_key="445cefmjypbfptjgnzgtwzpt"):
    if max_results is None:
        max_results = 5

    args = []

    base_url = "https://ieeexploreapi.ieee.org/api/v1/search/articles"

    params = {
        "apikey": api_key,
        "querytext": query,
        "max_records": max_results,
        "start_year": start_year,
        "end_year": end_year,
        "format": "json"  # Solicitar la respuesta en formato JSON
    }

    response = requests.get(base_url, params=params)

    # Imprimir la respuesta para depuración
    print("Status Code:", response.status_code)
    print("Response Text:", response.text)

    if response.status_code == 403:
        print("Error: Developer Inactive. Verifica que tu clave de API está activa.")
        return

    if response.status_code != 200:
        print("Error en la solicitud:", response.status_code)
        return

    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError as e:
        print("Error al decodificar JSON:", e)
        return

    for article in data.get('articles', []):
        paper_info = {
            "name": article.get('title', None),
            "doi": article.get('doi', None),
            "pdf_name": f"{article.get('doi', '').replace('/', '_')}.pdf" if article.get('doi') else None,
            "year": article.get('publication_year', None),
            "journal": article.get('publication_title', None),
            "authors": ', '.join(author.get('full_name', None) for author in article.get('authors', {}).get('authors', [])),
            "abstract": article.get('abstract', None)
        }

        args.append(paper_info)

        # Mostrar los metadatos de forma bonita
        print(f"Title: {paper_info['name']}")
        print(f"DOI: {paper_info['doi']}")
        print(f"PDF Name: {paper_info['pdf_name']}")
        print(f"Year: {paper_info['year']}")
        print(f"Journal: {paper_info['journal']}")
        print(f"Authors: {paper_info['authors']}")
        print(f"Abstract: {paper_info['abstract']}")
        print()

        # Descargar el PDF
        pdf_url = article.get('pdf_url', None)
        if pdf_url:
            pdf_response = requests.get(pdf_url)
            if pdf_response.status_code == 200:
                pdf_filename = os.path.join(dwn_dir, paper_info['pdf_name'])
                with open(pdf_filename, 'wb') as pdf_file:
                    pdf_file.write(pdf_response.content)
                print(f"PDF descargado: {pdf_filename}")
            else:
                print(f"Error al descargar el PDF: {pdf_response.status_code}")

    return args